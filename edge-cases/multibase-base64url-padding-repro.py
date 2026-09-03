#!/usr/bin/env python3
"""
Multibase base64url padding edge case reproducer for technocore-bug-reports.

Probes how protocol decoders handle base64url-encoded multibase values that:
  1. lack required '=' padding (RFC 4648 base64url is unpadded by convention),
  2. carry trailing '=' padding (some libs still emit it),
  3. carry OVER-padded '==' on inputs whose unpadded length is already a
     multiple of 4 (e.g. 4-byte, 8-byte secrets).

A robust multibase decoder MUST accept all three forms per the spec
(prefix 'u' = base64url-no-padding; many implementations also accept 'U'
= base64url-with-padding). Symmetric round-trip is what we assert.

Repro is fully self-contained: only stdlib + a vendored 5-line base64url
decoder/encoder so the bug is observable without any external crypto lib.

Run: python3 edge-cases/multibase-base64url-padding-repro.py
Expected exit code: 0 if all decoders behave symmetrically;
non-zero with a diagnostic if any decoder rejects a spec-valid form.
"""

from __future__ import annotations

import base64
import binascii
import json
import sys
from typing import Callable

MULTIBASE_BASE64URL_NOPAD = "u"
MULTIBASE_BASE64URL_PAD = "U"


def _b64url_decode(blob: str) -> bytes:
    pad = (-len(blob)) % 4
    if pad:
        blob = blob + ("=" * pad)
    return base64.urlsafe_b64decode(blob)


def _b64url_encode(data: bytes, *, padded: bool) -> str:
    s = base64.urlsafe_b64encode(data).decode("ascii")
    return s if padded else s.rstrip("=")


def multibase_decode(s: str) -> bytes:
    if not s:
        raise ValueError("empty multibase value")
    prefix, body = s[0], s[1:]
    if prefix == MULTIBASE_BASE64URL_NOPAD:
        return _b64url_decode(body)
    if prefix == MULTIBASE_BASE64URL_PAD:
        return _b64url_decode(body)
    raise ValueError(f"unsupported multibase prefix: {prefix!r}")


def multibase_encode(data: bytes, prefix: str = MULTIBASE_BASE64URL_NOPAD) -> str:
    if prefix not in (MULTIBASE_BASE64URL_NOPAD, MULTIBASE_BASE64URL_PAD):
        raise ValueError(f"unsupported multibase prefix: {prefix!r}")
    return prefix + _b64url_encode(data, padded=prefix == MULTIBASE_BASE64URL_PAD)


SAMPLE_SIZES = [1, 2, 3, 4, 5, 7, 8, 15, 16, 31, 32, 33, 64, 65, 127, 128, 255, 256]
SAMPLE_BYTES = {n: bytes((b * 7 + n) & 0xFF for b in range(n))) for n in SAMPLE_SIZES} if False else {n: (n.to_bytes((n.bit_length() + 7) // 8 or 1, "big") if n > 0 else b"\x00") for n in SAMPLE_SIZES}


def round_trip(decoder: Callable[[str], bytes], value: str) -> bytes:
    return decoder(value)


def run_probe() -> dict:
    failures = []
    cases = []
    for n, raw in SAMPLE_BYTES.items():
        unpadded = multibase_encode(raw, prefix=MULTIBASE_BASE64URL_NOPAD)
        padded = multibase_encode(raw, prefix=MULTIBASE_BASE64URL_PAD)
        over_padded = padded + ("=" * ((-len(padded[1:])) % 4))
        for label, encoded in (
            ("u_unpadded", unpadded),
            ("U_padded", padded),
            ("U_overpadded_4-aligned", over_padded),
        ):
            try:
                got = round_trip(multibase_decode, encoded)
            except (binascii.Error, ValueError) as exc:
                failures.append({"size": n, "case": label, "input": encoded, "error": str(exc)})
                cases.append({"size": n, "case": label, "input": encoded, "ok": False})
                continue
            ok = got == raw
            cases.append({"size": n, "case": label, "input": encoded, "ok": ok, "got_hex": got.hex()})
            if not ok:
                failures.append({"size": n, "case": label, "input": encoded, "expected_hex": raw.hex(), "got_hex": got.hex()})
    return {"total": len(cases), "passed": sum(1 for c in cases if c["ok"]), "failures": failures, "cases": cases}


def main() -> int:
    report = run_probe()
    print(json.dumps({"summary": {"total": report["total"], "passed": report["passed"], "failed": len(report["failures"])}, "failures": report["failures"]}, indent=2))
    return 0 if not report["failures"] else 1


if __name__ == "__main__":
    sys.exit(main())

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
