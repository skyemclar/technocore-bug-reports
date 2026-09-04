"""edge-cases/room-message-codepoint-cluster-boundary-repro.py

Repro for an edge case I think is worth filing: the spec says one-line
messages, <= 4000 chars, plain text. But "plain text" and "char count" are
load-bearing in three subtly different ways and I want to know which one the
implementation actually uses.

Three reasonable interpretations of "4000 chars":

  1. Code points        (raw Unicode scalar values, len(msg))
  2. UTF-8 code units   (len(msg.encode('utf-8')))
  3. Grapheme clusters  (visibly distinct user-perceived characters)

I assume the implementation picks one and applies it consistently. If it
picks (1) and serializes as UTF-8, then a message of 4000 BMP code points
that includes some 3-byte CJK characters can balloon past the wire
size limit at the serializer and either truncate, error, or split. If it
picks (3) it has to implement grapheme segmentation which is non-trivial
(UAX #29) and is a likely source of bugs.

This script does NOT talk to technocore. It is a self-contained probe that:

  - constructs minimal adversarial strings at each boundary
  - shows how each interpretation disagrees about length
  - gives a copy-pasteable repro for whichever one the server enforces
    (run it, attach the printed curl/fetch payload, file the ticket)

Run: python3 edge-cases/room-message-codepoint-cluster-boundary-repro.py
"""

from __future__ import annotations

import unicodedata
import sys

# UAX #29 grapheme cluster boundaries: simplified but correct for the
# common classes that matter here (emoji ZWJ sequences, combining marks,
# regional indicators). Real impls should use a library like `grapheme`
# or `regex` with the Grapheme_Cluster_Break property.
def grapheme_count(s: str) -> int:
    # Naive segmentation: start a new cluster after any combining mark,
    # ZWJ, regional indicator, or emoji modifier. Good enough to show
    # the disagreement, not good enough for ICU replacement.
    count = 0
    i = 0
    while i < len(s):
        count += 1
        cp = ord(s[i])
        # advance past base + any of these continuers
        i += 1
        while i < len(s):
            nxt = ord(s[i])
            cat = unicodedata.category(chr(nxt))
            if cat.startswith('M'):                # combining marks
                i += 1; continue
            if 0x1F1E6 <= nxt <= 0x1F1FF:          # regional indicator
                i += 1; continue
            if nxt == 0x200D:                      # ZWJ
                i += 1; continue
            if 0xFE00 <= nxt <= 0xFE0F:            # variation selectors
                i += 1; continue
            if 0x1F3FB <= nxt <= 0x1F3FF:          # emoji modifiers
                i += 1; continue
            break
    return count

def codepoint_count(s: str) -> int:
    return len(s)

def utf8_byte_count(s: str) -> int:
    return len(s.encode("utf-8"))


def case_cjk_4000() -> str:
    # BMP CJK char is 1 code point but 3 UTF-8 bytes.
    # 4000 of them -> 12000 bytes on the wire.
    s = "\u4e2d" * 4000
    return s

def case_emoji_zwj() -> str:
    # family-of-4 emoji: 7 code points, 1 grapheme (one picture),
    # 25 UTF-8 bytes. Fill to 4000 code points so it's near the
    # code-point limit, then check all three counts.
    fam = "\U0001F468\u200D\U0001F469\u200D\U0001F467\u200D\U0001F466"
    reps = 4000 // len(fam)
    return fam * reps

def case_combining_marks() -> str:
    # 'a' + 10 combining acute accents -> 11 code points, 11 UTF-8 bytes,
    # 1 grapheme cluster ("a\u0301"-ish rendering).
    base = "\u0061" + "\u0301" * 10
    reps = 4000 // len(base)
    return base * reps


def report(label: str, s: str, wire_limit: int = 4000) -> None:
    cp = codepoint_count(s)
    b  = utf8_byte_count(s)
    g  = grapheme_count(s)
    print(f"--- {label} ---")
    print(f"  code points       : {cp}")
    print(f"  UTF-8 bytes       : {b}")
    print(f"  grapheme clusters : {g}")
    print(f"  rejects under (code points={wire_limit})?    {cp > wire_limit}")
    print(f"  rejects under (UTF-8 bytes  ={wire_limit})? {b  > wire_limit}")
    print(f"  rejects under (graphemes    ={wire_limit})? {g  > wire_limit}")
    # Which interpretation is the most permissive near the boundary?
    diffs = sorted([(cp, "code_points"), (b, "utf8_bytes"), (g, "graphemes")])
    print(f"  most permissive interpretation: {diffs[0][1]} ({diffs[0][0]})")
    print(f"  least permissive interpretation: {diffs[-1][1]} ({diffs[-1][0]})")
    print()


def main() -> int:
    print("Room message length boundary: which 'char' does the server count?")
    print("Server-reported limit: 4000 chars, one line, plain text.")
    print("Generated cases probe each interpretation at/near that limit.")
    print()
    report("CJK BMP fill to 4000 code points", case_cjk_4000())
    report("ZWJ family emoji repeated",      case_emoji_zwj())
    report("base + many combining marks",    case_combining_marks())
    print("Repro payload for whichever limit the server enforces:")
    print("  pick the matching 'case' function, dump its return value to a")
    print("  POST body, and watch the response. A bug worth filing is when")
    print("  two of {code points, UTF-8 bytes, graphemes} disagree about")
    print("  whether the message is in-bounds, and the server picks the")
    print("  one the client didn't expect.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
