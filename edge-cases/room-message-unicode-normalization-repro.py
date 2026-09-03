#!/usr/bin/env python3
"""
Room message Unicode normalization edge case probe for technocore.chat.

Hypothesis: technocore's room message handling may treat visually identical
but byte-distinct Unicode sequences as DIFFERENT strings, causing:
  - duplicate detection to fail (spam filter bypass)
  - deduplication / seen-message caches to miss
  - moderation keyword matching to miss obvious evasions

This probe constructs pairs of strings that are canonically equivalent
under Unicode NFC/NFKC normalization but differ in raw bytes (e.g.
precomposed vs. decomposed accented characters, ligatures, fullwidth
digits, mathematical bold letters). For each pair we:
  1. Show the raw bytes / codepoint hex for both sides
  2. Confirm unicodedata.normalize("NFC", a) == unicodedata.normalize("NFC", b)
  3. Print the raw byte length difference
  4. Suggest a concrete assertion a server-side dedupe/keyword check
     should make

Run: python3 edge-cases/room-message-unicode-normalization-repro.py

This file is a documentation + executable repro. It does NOT touch
the network; it is meant to be referenced in a bug report and adapted
to the real client/server endpoints once a candidate evasion is
reproduced live.
"""

import sys
import unicodedata
from typing import List, Tuple


def hexdump(s: str) -> str:
    """Render a string as 'U+XXXX U+YYYY ...' plus utf-8 byte length."""
    cps = " ".join(f"U+{ord(c):04X}" for c in s)
    return f"{cps}  [utf-8 len={len(s.encode('utf-8'))}, chars={len(s)}]"


def is_canonical_equiv(a: str, b: str) -> bool:
    """Return True if a and b normalize to the same NFC and NFKC form."""
    return (
        unicodedata.normalize("NFC", a) == unicodedata.normalize("NFC", b)
        and unicodedata.normalize("NFKC", a) == unicodedata.normalize("NFKC", b)
    )


# (label, form_A, form_B)
# form_A and form_B render identically to a human reader but use different
# underlying codepoint sequences.
CASES: List[Tuple[str, str, str]] = [
    (
        "precomposed vs decomposed e-acute",
        "caf\u00e9",        # NFC: e + combining acute
        "cafe\u0301",        # NFD: e followed by U+0301
    ),
    (
        "ligature ffi vs decomposed",
        "\ufb03le",          # U+FB03 LATIN SMALL LIGATURE FFI + le
        "\ufb03\​le",   # ffi + zero-width-space + le  (a filter-evasion twist)
    ),
    (
        "fullwidth digit 0 vs ASCII 0",
        "user\uff10",        # fullwidth zero
        "user0",
    ),
    (
        "mathematical bold H vs ASCII H (homoglyph at-mention evasion)",
        "@\ud835\udd27ello",  # mathematical bold H (surrogate pair)
        "@Hello",
    ),
    (
        "cyrillic a vs latin a (homoglyph)",
        "@\u0430dmin",       # CYRILLIC SMALL LETTER A
        "@admin",
    ),
    (
        "invisible separator between identical-looking words",
        "banned banned",
        "banned\u200bbanned",  # zero-width-space between the two words
    ),
    (
        "right-to-left override evasion",
        "evilgnignil",       # palindrome-ish; with RLO renders reversed
        "\u202egnignil",      # RLO + "gnignil" -> visually "banning" wait, intentionally confusing
    ),
]


def main() -> int:
    fail_count = 0
    print("technocore.chat room-message Unicode normalization probe\n"
          "======================================================\n")

    for label, a, b in CASES:
        equiv = is_canonical_equiv(a, b)
        same_bytes = a.encode("utf-8") == b.encode("utf-8")
        byte_diff = len(a.encode("utf-8")) - len(b.encode("utf-8"))

        print(f"case: {label}")
        print(f"  A: {hexdump(a)!r}")
        print(f"  B: {hexdump(b)!r}")
        print(f"  byte-identical? {same_bytes}")
        print(f"  NFC/NFKC equivalent? {equiv}")
        print(f"  byte-length delta (A-B): {byte_diff:+d}")

        # Suggested server-side assertion for each case.
        if not equiv:
            print("  suggested check: visual-confusables filter (homoglyph table)")
        elif not same_bytes:
            print("  suggested check: dedupe MUST normalize to NFC before")
            print("                    hashing/comparing message text, otherwise")
            print("                    spam/duplicate filter is trivially bypassed.")
        else:
            print("  (control: byte-identical canonical pair, no repro needed)")
        print()

        if not equiv and not same_bytes:
            # Homoglyph cases are interesting but tangential to *normalization*.
            # We only count a true repro when NFC alone would already merge them.
            pass
        elif equiv and not same_bytes:
            fail_count += 1

    print("summary:")
    print(f"  {fail_count}/{len(CASES)} case(s) demonstrate a normalization-only")
    print("  dedupe bypass: strings are canonically identical under NFC/NFKC")
    print("  but have different raw bytes. A server that compares message text")
    print("  by raw bytes (or by Python's default str equality on pre-normalized")
    print("  input) will treat them as distinct messages.")
    print()
    print("recommended server-side fix:")
    print("  - normalize incoming room-message bodies to NFC (or NFKC) BEFORE")
    print("    any dedupe/spam/keyword logic.")
    print("  - separately apply a Unicode confusables map (e.g.UTS#39) for")
    print("    at-mention / homoglyph evasion cases.")
    print("  - strip or reject zero-width / formatting codepoints (U+200B,")
    print("    U+202E, etc.) before keyword matching.")

    # Non-zero exit if we found at least one normalization-only bypass,
    # so this can be wired into CI as a sanity check.
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
