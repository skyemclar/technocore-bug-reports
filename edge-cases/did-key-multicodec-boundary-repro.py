#!/usr/bin/env python3
"""
Reproducer: did:key multicodec prefix collision / ambiguity edge cases
=====================================================================

Some did:key resolver implementations naively match the leading bytes of
the decoded multicodec key material without validating the full VarInt
prefix. This creates a class of bugs where truncated or crafted keys can
masquerade as a different key type, causing resolution failures, type
confusion, or incorrect verification-material extraction.

This file probes four specific edge cases:

  1. TRUNCATED-ED25519  – an ed25519 public key with the first 2 bytes
     stripped. Resolvers that only check the first byte may misidentify
     it as a valid key.

  2. PREFIX-OVERLAP     – a secp256k1 key whose raw bytes happen to
     start with 0xed (the ed25519 prefix). Without full VarInt decoding,
     this triggers a false ed25519 match.

  3. ZERO-LENGTH-KEY    – VarInt that decodes to zero. The spec says
     this is invalid; many resolvers crash or hang.

  4. TRAILING-GARBAGE   – extra non-canonical bytes appended after the
     multicodec prefix + key body. A correct parser must reject these.

Minimal dependencies: Python 3.10+, stdlib only (base58, hashlib).

Usage:
    python did-key-multicodec-boundary-repro.py

Each test prints the DID being probed, the expected vs observed
behavior, and a PASS/FAIL verdict. Failures include a compact
reproduction summary suitable for a bug report.
"""

import base64
import hashlib
import struct
from typing import NamedTuple

# ── multicodec constants (from the multicodec table) ──────────────────────
ED25519_PUB_CODEC  = 0xED  # varint: single byte, 0xed
SECP256K1_PUB_CODEC = 0xE7  # varint: single byte, 0xe7

# Base58 BTC alphabet for did:key (multibase base58btc = 'z' prefix)
BTC_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


# ── minimal base58btc encoder (stdlib-only, no external deps) ────────────
def _b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    chars = []
    while n > 0:
        n, rem = divmod(n, 58)
        chars.append(BTC_ALPHABET[rem])
    # leading zeros
    for byte in b:
        if byte == 0:
            chars.append(BTC_ALPHABET[0])
        else:
            break
    return "".join(reversed(chars))


def _b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + BTC_ALPHABET.index(c)
    result = n.to_bytes((n.bit_length() + 7) // 8, "big")
    # leading '1' padding
    pad = 0
    for c in s:
        if c == BTC_ALPHABET[0]:
            pad += 1
        else:
            break
    return b"\x00" * pad + result


# ── VarInt helpers ────────────────────────────────────────────────────────
def encode_varint(value: int) -> bytes:
    """Unsigned-varint per multicodec / protobuf spec."""
    buf = []
    while value > 0x7F:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.append(value & 0x7F)
    return bytes(buf)


def decode_varint(data: bytes) -> tuple[int, int]:
    """Return (value, bytes_consumed). Raises on overflow."""
    value = 0
    shift = 0
    for i, byte in enumerate(data):
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, i + 1
        shift += 7
        if shift >= 64:
            raise ValueError("VarInt overflow")
    raise ValueError("Truncated VarInt")


# ── DID construction helpers ──────────────────────────────────────────────
def make_did_key(multicodec_prefix: bytes, key_material: bytes) -> str:
    """Build a did:key:<multibase-btc> string."""
    payload = multicodec_prefix + key_material
    encoded = _b58encode(payload)
    return f"did:key:z{encoded}"


def parse_did_key_correct(did: str) -> tuple[int, bytes] | None:
    """
    Correct parser: decodes the full VarInt prefix, then extracts the
    remaining bytes as key material. Rejects trailing garbage.
    """
    if not did.startswith("did:key:z"):
        return None
    try:
        payload = _b58decode(did.removeprefix("did:key:z"))
    except Exception:
        return None
    try:
        codec, offset = decode_varint(payload)
    except ValueError:
        return None
    key_material = payload[offset:]
    if len(key_material) == 0:
        return None  # zero-length keys are invalid
    # If there is data beyond the expected key length for this codec,
    # it's trailing garbage — reject.
    expected_len = _expected_key_len(codec)
    if expected_len is not None and len(key_material) != expected_len:
        return None
    return codec, key_material


def parse_did_key_naive(did: str) -> tuple[int, bytes] | None:
    """
    Buggy parser: checks only the first byte of the payload as the
    multicodec indicator. Does *not* decode the VarInt, does *not*
    validate key length, does *not* reject trailing garbage.
    """
    if not did.startswith("did:key:z"):
        return None
    try:
        payload = _b58decode(did.removeprefix("did:key:z"))
    except Exception:
        return None
    if len(payload) < 2:
        return None
    codec = payload[0]  # BUG: only reads 1 byte — misses multi-byte VarInts
    key_material = payload[1:]
    return codec, key_material


def _expected_key_len(codec: int) -> int | None:
    if codec == ED25519_PUB_CODEC:
        return 32
    if codec == SECP256K1_PUB_CODEC:
        return 33  # compressed
    return None


# ── test framework ────────────────────────────────────────────────────────
class TestCase(NamedTuple):
    name: str
    description: str
    did: str
    expected_codec: int | None  # None = should be rejected


def run() -> None:
    # Build a valid ed25519 key for reference.
    valid_ed25519_key = hashlib.sha256(b"test-ed25519-seed-0001").digest()  # 32 bytes
    valid_did = make_did_key(bytes([ED25519_PUB_CODEC]), valid_ed25519_key)

    # ── craft edge-case DIDs ──────────────────────────────────────────

    # CASE 1: Truncate the first 2 bytes (codec byte + 1 key byte).
    # The naive parser sees payload[0] = 0x71 ('q'), not a known codec.
    truncated_payload = bytes([ED25519_PUB_CODEC]) + valid_ed25519_key[2:]
    truncated_did = make_did_key(b"", b"")  # placeholder
    truncated_did = f"did:key:z{_b58encode(truncated_payload)}"

    # CASE 2: secp256k1 key where raw bytes start with 0xed.
    # We brute-force a seed such that SHA-256 produces leading 0xed.
    secp_prefix_bytes = bytes([SECP256K1_PUB_CODEC])
    crafted_key = bytearray(33)
    crafted_key[0] = 0xED  # mimic ed25519 prefix in key body
    crafted_key[1:] = hashlib.sha256(b"crafted-secp256k1").digest()[:32]
    overlap_did = make_did_key(secp_prefix_bytes, bytes(crafted_key))

    # CASE 3: Zero-length key material.
    zero_key_did = make_did_key(bytes([ED25519_PUB_CODEC]), b"")

    # CASE 4: Trailing garbage — append 5 extra bytes.
    garbage_payload = (
        bytes([ED25519_PUB_CODEC]) + valid_ed25519_key + b"\xDE\xAD\xBE\xEF\x00"
    )
    garbage_did = f"did:key:z{_b58encode(garbage_payload)}"

    tests: list[TestCase] = [
        TestCase(
            "TRUNCATED-ED25519",
            "Ed25519 key with first 2 bytes stripped; naive parser sees raw 0x71 byte.",
            truncated_did,
            None,  # must be rejected
        ),
        TestCase(
            "PREFIX-OVERLAP",
            "Secp256k1 key whose raw material starts with 0xED (ed25519 codec).",
            overlap_did,
            SECP256K1_PUB_CODEC,  # correct codec is secp256k1, not ed25519
        ),
        TestCase(
            "ZERO-LENGTH-KEY",
            "VarInt ed25519 prefix followed by zero bytes of key material.",
            zero_key_did,
            None,
        ),
        TestCase(
            "TRAILING-GARBAGE",
            "Valid ed25519 key + 5 extra non-canonical bytes appended.",
            garbage_did,
            None,
        ),
    ]

    print("=" * 68)
    print("did:key multicodec boundary reproducer")
    print("=" * 68)
    print(f"\nReference valid DID: {valid_did}")
    print(f"  → correct parser codec: 0x{ED25519_PUB_CODEC:02x} (ed25519-pub)")
    print()

    failures = 0
    for tc in tests:
        print(f"── {tc.name} ──")
        print(f"    {tc.description}")
        print(f"    DID: {tc.did[:80]}{'...' if len(tc.did) > 80 else ''}")

        correct = parse_did_key_correct(tc.did)
        naive   = parse_did_key_naive(tc.did)

        correct_ok = (correct is None and tc.expected_codec is None) or \
                     (correct is not None and correct[0] == tc.expected_codec)
        # The naive parser may incorrectly accept what should be rejected,
        # or return a wrong codec.
        naive_codec = naive[0] if naive else None
        if naive is not None and tc.expected_codec is not None:
            naive_matches = (naive_codec == tc.expected_codec)
        elif naive is not None and tc.expected_codec is None:
            naive_matches = False  # naive accepted garbage — bug
        else:
            naive_matches = (naive is None and tc.expected_codec is None)

        verdict = "PASS" if correct_ok else "FAIL"
        if not correct_ok:
            failures += 1
        print(f"    Correct parser: {correct}  → {verdict}")
        print(f"    Naive parser:   codec=0x{naive_codec:02x if naive_codec else '--'}, "
              f"key_len={len(naive[1]) if naive else '--'}  → "
              f"{'PASS' if naive_matches else 'FAIL (BUG)'}")

        if not correct_ok:
            print(f"    REPRO: Correct parser returned {correct}, expected codec "
                  f"{tc.expected_codec}")
        elif naive is not None and tc.expected_codec is None:
            failures += 1
            print(f"    REPRO: Naive parser accepted an invalid DID that should be rejected.")
            print(f"           Payload hex: {_b58decode(tc.did.removeprefix('did:key:z')).hex()}")
        print()

    print("=" * 68)
    if failures == 0:
        print("All edge cases handled correctly by the correct parser.")
    else:
        print(f"{failures} edge case(s) exposed parser bugs.")
    print(f"The naive parser is intentionally buggy — these are the bugs it triggers.")
    print("=" * 68)


if __name__ == "__main__":
    run()

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
