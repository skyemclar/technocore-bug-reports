"""
Repro: DID:key Ed25519 prefix invariant under non-canonical encodings.

Spec (W3C did:key): an Ed25519 did:key MUST be
  did:key:z6Mk...   (multibase 'z' base58-btc + multicodec 0xED 0x01).
The 0xED 0x01 prefix MUST be exactly 2 bytes before the 32-byte raw public key.

Bug hypothesis: some client libraries accept multibase 'Z' (base64) or 'M'
(hex) and silently coerce, producing did:key strings whose key bytes do NOT
start with 0xED 0x01 when re-decoded canonically. Other libraries then reject
or mis-route these strings. This script enumerates the non-canonical encodings
expected to be rejected, and asserts the canonical round-trip.

Run: python3 edge-cases/did-key-ed25519-prefix-invariant-repro.py
Exit 0 = invariant holds for the canonical form. The non-canonical cases are
printed as expected failures for human triage.

This file is a self-contained repro and is safe to run offline.
"""

import base64
import binascii
import sys

# Fixed test vector: a known-good 32-byte Ed25519 public key (RFC 8032 test 1, A).
RAW_PUBKEY = bytes.fromhex(
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af019a73f17a4d27"
)
assert len(RAW_PUBKEY) == 32, "Ed25519 public key must be 32 bytes"

# Multicodec prefix for Ed25519PublicKey per did:key spec.
ED25519_MULTICODEC = b"\xed\x01"

# Canonical: multibase 'z' (base58-btc) over (multicodec || raw key).
def canonical_did_key(raw_pub: bytes) -> str:
    assert len(raw_pub) == 32
    payload = ED25519_MULTICODEC + raw_pub
    # base58-btc alphabet
    ALPH = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = int.from_bytes(payload, "big")
    enc = bytearray()
    while n > 0:
        n, r = divmod(n, 58)
        enc.append(ALPH[r])
    # preserve leading zero bytes as leading '1's
    for b in payload:
        if b == 0:
            enc.append(ALPH[0])
        else:
            break
    enc.reverse()
    return "did:key:z" + enc.decode("ascii")

# Decoders for the non-canonical encodings we expect to be rejected.
def decode_multibase(s: str):
    code, body = s[0], s[1:].encode("ascii")
    if code == "z":  # base58-btc
        ALPH = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        n = 0
        for ch in body:
            i = ALPH.find(ch)
            assert i >= 0, f"invalid base58 char {ch!r}"
            n = n * 58 + i
        # count leading '1's as leading zero bytes
        pad = 0
        for ch in body:
            if ch == ord(ALPH[0:1]):
                pad += 1
            else:
                break
        raw = n.to_bytes((n.bit_length() + 7) // 8 or 1, "big") if n else b""
        return b"\x00" * pad + raw
    if code == "M":  # base16 (hex), uppercase per multibase table
        return binascii.unhexlify(body)
    if code == "Z":  # base64 (std alphabet, no padding required)
        # multibase 'Z' is base64-padded; tolerate missing padding for robustness
        pad = (-len(body)) % 4
        return base64.b64decode(body + b"=" * pad)
    raise ValueError(f"unknown multibase code {code!r}")

def invariant_check(did: str, label: str):
    prefix, body = did.split(":", 2)[1], did.split(":", 2)[2]
    if prefix != "key":
        return label, False, f"non-key method: {prefix!r}"
    raw = decode_multibase(body)
    ok = raw.startswith(ED25519_MULTICODEC) and len(raw) == 34
    return label, ok, raw.hex()

# Build the four candidate did:key strings for the same 32-byte key.
canon = canonical_did_key(RAW_PUBKEY)
hex_body = binascii.hexlify(ED25519_MULTICODEC + RAW_PUBKEY).decode("ascii").upper()
hex_did = "did:key:M" + hex_body
b64_body = base64.b64encode(ED25519_MULTICODEC + RAW_PUBKEY).decode("ascii").rstrip("=")
b64_did = "did:key:z" + b64_body  # note: WRONG multibase code 'z' on b64 body

cases = [
    ("canonical base58-btc", canon),
    ("hex via multibase 'M' (valid alternative)", hex_did),
    ("base64 body under multibase 'z' (INVALID — wrong code)", b64_did),
]

print(f"raw pubkey : {RAW_PUBKEY.hex()}")
print(f"canonical  : {canon}")
print()
fail = 0
for label, did in cases:
    name, ok, info = invariant_check(did, label)
    flag = "PASS" if ok else "FAIL"
    print(f"[{flag}] {name}\n        did = {did}\n        decoded prefix bytes = {info}")
    if not ok and "INVALID" not in label:
        fail += 1

# Invariant: the canonical string MUST round-trip and start with 0xed01 + 32-byte key.
assert canon.startswith("did:key:z")
_, ok, decoded = invariant_check(canon, "canonical")
assert ok and decoded == (ED25519_MULTICODEC + RAW_PUBKEY).hex(), (
    f"canonical did:key did not round-trip: {decoded!r}"
)
print()
print("invariant holds: canonical did:key round-trips with 0xed01 prefix.")
sys.exit(0 if fail == 0 else 1)

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
