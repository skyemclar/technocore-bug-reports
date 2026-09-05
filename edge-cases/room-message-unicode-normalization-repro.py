"""
edge-cases/room-message-unicode-normalization-repro.py

Focus: probe how the technocore.chat room-message endpoint handles strings that
are visually identical but differ in Unicode normalization form (NFC vs NFD vs
NFKC vs NFKD), and strings containing confusable / mixed-script characters that
could enable homograph-style spoofing of room identity or display names.

Why this matters:
  - If the server canonicalizes messages before storage/dedup, two distinct
    client-side compositions of the same logical string will collide.
  - If it does NOT canonicalize, lookups (search, moderation, replay
    protection) become inconsistent across clients.
  - If display-name fields accept homoglyphs without script-mixing checks,
    impersonation is trivial.

Repro is self-contained: talks HTTP to technocore.chat using only the stdlib.
Run with: python3 edge-cases/room-message-unicode-normalization-repro.py
"""

from __future__ import annotations

import json
import os
import sys
import unicodedata
import urllib.error
import urllib.request
from typing import Tuple

BASE = os.environ.get("TECHNOCORE_BASE", "https://technocore.chat")
ROOM = os.environ.get("TECHNOCORE_ROOM", "lobby")
SENDER = os.environ.get(
    "TECHNOCORE_SENDER_DID", "did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy"
)


def _byte_equal(a: str, b: str) -> bool:
    return a.encode("utf-8") == b.encode("utf-8")


def post_text(text: str, label: str) -> Tuple[int, dict, bytes]:
    body = json.dumps(
        {"room": ROOM, "sender": SENDER, "text": text, "client_tag": label}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/rooms/{ROOM}/messages",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, dict(resp.getheaders()), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read() or b""


def case(label: str, s: str) -> dict:
    code, hdrs, raw = post_text(s, label)
    parsed = {}
    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
    except Exception:
        parsed = {"_raw": raw[:200].decode("utf-8", "replace")}
    return {
        "label": label,
        "status": code,
        "id": parsed.get("id"),
        "text_echo": parsed.get("text"),
        "codepoints": [hex(ord(c)) for c in s],
        "nfc": unicodedata.normalize("NFC", s),
        "nfd": unicodedata.normalize("NFD", s),
    }


def main() -> int:
    # e + combining acute (U+0065 U+0301) vs precomposed e-acute (U+00E9)
    decomposed = "caf\u0065\u0301"
    composed = "caf\u00e9"

    # compatibility variants: fullwidth, superscript, ligature
    compat_fullwidth = "\uff28\uff45\uff4c\uff4c\uff4f"  # "Hello"
    compat_ascii = "Hello"

    # mixed-script homograph: Latin 'a' + Cyrillic 'a' (U+0430)
    mixed = "p\u0430ypal"  # looks like "paypal" but mixes scripts

    cases = [
        case("nfd-e-acute", decomposed),
        case("nfc-e-acute", composed),
        case("fullwidth-hello", compat_fullwidth),
        case("ascii-hello", compat_ascii),
        case("mixed-script-paypal", mixed),
    ]

    print("== normalization repro ==")
    for c in cases:
        print(json.dumps(c, ensure_ascii=False))

    # Verdict
    nfd = cases[0]
    nfc = cases[1]
    same_id = (
        nfd.get("id") is not None
        and nfd.get("id") == nfc.get("id")
    )
    print("--")
    print(f"NFD byte-equal NFC? {_byte_equal(decomposed, composed)}")
    print(f"Server treated as same message (idempotent)? {same_id}")
    print("If False, dedup/search will diverge across clients composing the")
    print("same visible string differently. File a bug with the JSON above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
