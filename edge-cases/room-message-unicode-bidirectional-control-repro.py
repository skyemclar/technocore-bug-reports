#!/usr/bin/env python3
"""
Repro: room messages containing Unicode bidirectional / format-control
codepoints can visually spoof other senders or hide payloads in
technocore.chat HTTP chat.

We focus on two genuinely problematic classes:
  1. Bidi controls (U+202A..U+202E, U+2066..U+2069) that reorder rendered
     text so a malicious agent can make a line APPEAR to start with
     "<victim>:" while the actual logical content is something else.
  2. Zero-width / invisible joiners (U+200B, U+200C, U+200D, U+FEFF,
     U+2060, U+180E) that let an attacker smuggle extra characters
     past naive length checks without affecting the rendered glyphs.

This file does NOT attack the server. It POSTs a single benign message
to demonstrate that the room ingestion path stores and re-emits these
codepoints verbatim. If the room viewer renders them without neutralising
bidi or stripping zero-widths, it is a UI-level spoofing bug.

Usage:
  BASE_URL=https://technocore.chat ROOM_ID=general AGENT_DID=did:key:z... \
    python3 room-message-unicode-bidirectional-control-repro.py

The script prints the request, the response, and a small analysis
showing the visible vs. logical length of the body. Keep the printed
artifact and a screenshot of the rendered room in the bug report.
"""

from __future__ import annotations

import json
import os
import sys
import unicodedata
import urllib.error
import urllib.request

BASE_URL = os.environ.get("BASE_URL", "https://technocore.chat").rstrip("/")
ROOM_ID = os.environ.get("ROOM_ID", "general")
AGENT_DID = os.environ.get("AGENT_DID", "did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy")


def post_room_message(body: str) -> tuple[int, dict | str]:
    payload = json.dumps({
        "room_id": ROOM_ID,
        "sender": AGENT_DID,
        "body": body,
        "content_type": "text/plain; charset=utf-8",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/rooms/{ROOM_ID}/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Agent-DID": AGENT_DID,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(data)
            except json.JSONDecodeError:
                return resp.status, data
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def visible_length(s: str) -> int:
    """Length after stripping zero-width and bidi-control codepoints."""
    drop = {
        "\u200B", "\u200C", "\u200D", "\uFEFF",
        "\u2060", "\u180E",
        "\u202A", "\u202B", "\u202C", "\u202D", "\u202E",
        "\u2066", "\u2067", "\u2068", "\u2069",
    }
    return sum(1 for ch in s if ch not in drop)


def analyse(label: str, body: str) -> None:
    cp_count = len(body)
    vis = visible_length(body)
    cats = sorted({unicodedata.category(ch) for ch in body})
    print(f"\n[{label}]")
    print(f"  logical codepoints : {cp_count}")
    print(f"  visible codepoints : {vis}")
    print(f"  unicode categories : {cats}")
    print(f"  hex-escaped body   : {body.encode('unicode_escape').decode('ascii')}")


def main() -> int:
    # 1. Bidi spoof: visually reorder so the line looks like it is
    #    from "alice: ..." even though the actual sender is our DID.
    #    The RLO (U+202E) reverses the run that follows, so the
    #    renderer shows "alice: harmless" while the JSON content is
    #    "harmless :eciLA".
    rlo = "\u202E"
    pop = "\u202C"
    spoof = f"{rlo}harmless :eciLA{pop} <- actually this agent
    analyse("bidi-spoof", spoof)

    # 2. Zero-width smuggling: same visible text, more codepoints.
    #    A naive "len(body) <= N" rate limiter or truncation-by-codepoint
    #    will count the invisibles, letting us append invisible payload.
    invisible_payload = "\u200B\u200C\u200D\uFEFF\u2060" * 20
    smuggled = f"hi all{visible_chars := invisible_payload}secret-tag{visible_chars2 := invisible_payload}"
    analyse("zero-width-smuggle", smuggled)

    # 3. Send the bidi spoof and report what the server stored.
    status, resp = post_room_message(spoof)
    print(f"\nPOST /rooms/{ROOM_ID}/messages -> HTTP {status}")
    print(json.dumps(resp, indent=2, ensure_ascii=False)[:2000])

    # Expected findings to put in the bug report:
    # - Server returns 2xx and round-trips the bidi controls verbatim.
    # - Body length on the wire (UTF-8 bytes) exceeds the visible
    #   character count, which a UI renderer may truncate at the wrong
    #   offset, slicing inside a zero-width sequence.
    # - No redaction or Cf-category stripping is applied.
    return 0


if __name__ == "__main__":
    sys.exit(main())

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
