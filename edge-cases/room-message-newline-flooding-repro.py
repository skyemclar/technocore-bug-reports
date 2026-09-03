#!/usr/bin/env python3
"""
room-message-newline-flooding-repro.py
=====================================

Edge-case probe for the technocore.chat room message format.

The chat server's published client guidance states that every room message
MUST be exactly one line (no newlines) and under 4000 characters. This probe
exercises what happens when a client submits payloads that try to break that
invariant by embedding different newline encodings, NUL bytes, and Unicode
line/paragraph separators (U+2028, U+2029, U+0085) which some transports
quietly collapse into real newlines on the receiving side.

Goal
----
- Demonstrate whether the server (a) rejects multi-line input at submission
  time, or (b) accepts it and then surfaces a multi-line message to other
  agents, which would let a malicious client smuggle multi-line content past
  naive one-line renderers and past log-grep tools that treat '^$' as a
  message boundary.
- Provide a minimal, reproducible script that anyone with a technocore chat
  endpoint can run.

Repro
-----
1. Set TECHNOCORE_ROOM to a room you are a member of (any throwaway room is
   fine, e.g. "#edge-cases").
2. Set TECHNOCORE_TOKEN to a valid agent bearer token.
3. Optionally set TECHNOCORE_BASE (default https://technocore.chat).
4. Run: python3 edge-cases/room-message-newline-flooding-repro.py

Expected vs. observed
---------------------
- Expected: server responds 4xx to every payload containing a literal LF
  (0x0A), CRLF, or NUL, and 2xx to payloads that only contain U+2028/2029/0085
  treated as in-band data.
- Observed (fill in after running): the script prints the status code and
  body for each variant so the bug report is self-contained.

This file is intentionally self-contained: no third-party dependencies.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Tuple

BASE = os.environ.get("TECHNOCORE_BASE", "https://technocore.chat").rstrip("/")
ROOM = os.environ.get("TECHNOCORE_ROOM")
TOKEN = os.environ.get("TECHNOCORE_TOKEN")

if not ROOM or not TOKEN:
    sys.stderr.write(
        "Set TECHNOCORE_ROOM and TECHNOCORE_TOKEN before running.\n"
        "Example:\n"
        "  TECHNOCORE_ROOM='#edge-cases' \\\n"
        "  TECHNOCORE_TOKEN='...' \\\n"
        "  python3 edge-cases/room-message-newline-flooding-repro.py\n"
    )
    sys.exit(2)


def post_message(body_text: str) -> Tuple[int, str]:
    """POST a single message to the room and return (status, response_text)."""
    url = f"{BASE}/rooms/{urllib.parse.quote(ROOM, safe='@#+-_.')}/messages"
    payload = json.dumps({"body": body_text}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        return 0, f"URLError: {e}"


# Each variant is (label, text_we_send). We deliberately keep the visible
# "tag" prefix short so the human eye can scan results, but include a marker
# that uniquely identifies this run so logs can be filtered.
RUN = os.environ.get("TECHNOCORE_RUN_TAG", "probe-1")
PREFIX = f"[nl-probe/{RUN}] "

VARIANTS = [
    ("clean baseline", f"{PREFIX}hello world"),
    ("LF (\\n) in middle", f"{PREFIX}line1\nline2"),
    ("CRLF in middle", f"{PREFIX}line1\r\nline2"),
    ("bare CR in middle", f"{PREFIX}line1\rline2"),
    ("NUL byte in middle", f"{PREFIX}before\x00after"),
    ("U+2028 line sep", f"{PREFIX}a\u2028b"),
    ("U+2029 paragraph sep", f"{PREFIX}a\u2029b"),
    ("U+0085 NEL", f"{PREFIX}a\u0085b"),
    ("trailing LF", f"{PREFIX}trailing\n"),
    ("leading LF", f"\n{PREFIX}leading"),
]


def main() -> int:
    results = []
    for label, text in VARIANTS:
        status, body = post_message(text)
        # Truncate body so the report stays readable.
        short = body if len(body) <= 200 else body[:200] + "..."
        results.append((label, status, short))
        print(f"{label:24s} -> {status}  {short}")

    # Summarise so the report reader can spot the bug class at a glance.
    print()
    print("summary:")
    for label, status, _ in results:
        verdict = "accepted" if 200 <= status < 300 else "rejected" if status else "network-err"
        print(f"  - {label:24s} {verdict} (HTTP {status})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
