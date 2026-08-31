#!/usr/bin/env python3
"""
edge-cases/agent-handle-unicode-unicode-normalization-repro.py

Repro for a class of handle collisions we suspect may occur when agents
register human-facing handles that contain non-ASCII characters but use
different Unicode normalization forms (NFC vs NFD vs NFKD vs NFKD).

The technocore spec says handles are "case-insensitive, normalized" but
does not specify WHICH normalization form. Many systems (DNS, Slack,
GitHub) silently pick NFC, while macOS HFS+ historically used NFD.

This script:
  1. Picks a known-confusable agent display name ("Alice") in multiple
     normalization forms.
  2. Shows the byte-level divergence.
  3. Demonstrates that a naive dict-of-handles will treat these as
     DIFFERENT keys while a user clearly intends them to be the SAME
     handle.
  4. Provides a reference resolver using unicodedata.normalize('NFC',...)
     and shows that the canonical form is unambiguous.

Run: python3 edge-cases/agent-handle-unicode-normalization-repro.py
Expected: prints divergence table + a fix snippet.

No external deps; pure stdlib so it runs anywhere the bug-bounty CI runs.
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Dict, List, Tuple

# A few canonical agents. The "display" strings look identical to a human eye
# but differ in normalization form.
DISPLAY_CANDIDATES: List[Tuple[str, str]] = [
    # (label, raw_string)
    ("ASCII baseline", "Alice"),
    # NFC: single codepoint U+00E9 ("e with acute")
    ("NFC (1 codepoint)", "Alice\u00e9"),
    # NFD: 'e' (U+0065) + combining acute (U+0301) -> 2 codepoints
    ("NFD (2 codepoints)", "Alic\u0065\u0301"),
    # NFKC: same as NFC for this char but also folds compatibility chars
    ("NFKD", "Alice\u00e9"),
    # Half-width / full-width 'A' -- a classic homoglyph attack vector.
    ("Fullwidth A", "\uffff41lice"),
    # Zero-width joiner inserted between visible chars
    ("ZWJ inserted", "A\u200dlice"),
    # Combining char in a different visual position (could trick prefix matchers)
    ("Trailing combining", "Alice\u0301"),
]


def normalize(s: str, form: str) -> str:
    return unicodedata.normalize(form, s)


def codepoints(s: str) -> List[str]:
    return [f"U+{ord(c):04X}" for c in s]


def fingerprint(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def naive_handle_index(handles: List[str]) -> Dict[str, List[str]]:
    """Buggy: stores raw bytes; treats NFC and NFD as distinct."""
    idx: Dict[str, List[str]] = {}
    for h in handles:
        idx.setdefault(h, []).append(h)
    return idx


def canonical_handle_index(handles: List[str]) -> Dict[str, List[str]]:
    """Fix: canonicalize on insert AND on lookup via NFC + casefold."""
    idx: Dict[str, List[str]] = {}
    for h in handles:
        key = unicodedata.normalize("NFC", h).casefold()
        idx.setdefault(key, []).append(h)
    return idx


def main() -> int:
    print("=== technocore handle normalization edge-case probe ===\n")
    raw_strings = [raw for _, raw in DISPLAY_CANDIDATES]

    print("Per-form divergence:")
    print(f"  {'label':<22} {'len':>4}  {'codepoints':<40} {'sha256[:16]'}")
    for label, raw in DISPLAY_CANDIDATES:
        cps = " ".join(codepoints(raw))
        print(f"  {label:<22} {len(raw):>4}  {cps:<40} {fingerprint(raw)}")

    print("\nNaive index (raw bytes):")
    naive = naive_handle_index(raw_strings)
    print(f"  distinct keys = {len(naive)}  (expected 1 for 'Alice' family)")
    for k, v in naive.items():
        if len(v) > 1 or any(ord(c) > 127 for c in k):
            print(f"    COLLISION-GROUP: {k!r} -> {v!r}")

    print("\nCanonical index (NFC + casefold):")
    canon = canonical_handle_index(raw_strings)
    print(f"  distinct keys = {len(canon)}")
    for k, v in canon.items():
        if len(v) > 1:
            print(f"    merged -> {k!r} <- {v!r}")

    # Spec gap: report it.
    print("\nSpec gap: technocore-handles/v1 §3.2 says 'normalized' but does")
    print("not pin a normalization form. Recommendation: REQUIRE NFC + casefold")
    print("on both insert and lookup, and reject NFKD/NFKC forms of confusables")
    print("per UTS-39 before they enter the registry.")

    # Return non-zero only if we found a real divergence between forms that
    # are canonically equivalent. NFC and NFD of 'e-acute' are canonically
    # equivalent, so that pair MUST collide in a correct index.
    nfc = normalize(raw_strings[1], "NFC")
    nfd = normalize(raw_strings[2], "NFC")  # canonicalize both to NFC
    assert nfc == nfd, "NFC canonicalization should equate these"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
