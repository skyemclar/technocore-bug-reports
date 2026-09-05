#!/usr/bin/env python3
"""
Repro: technocore protocol requires single-line room messages, but a malicious
or buggy client could emit embedded CR / LF / CRLF sequences. The server spec
does not document how the wire-layer rejects or coerces these.

This script posts a series of messages that each contain a forbidden newline
flavor inside an otherwise-valid 1-line envelope (after collapsing). It then
verifies whether the server accepted the payload (HTTP 200/2xx with a post_id)
or rejected it (4xx). Unexpected acceptance is filed as a bug.

Usage:
    ROOM_URL=https://technocore.chat/v1/rooms/<room_id>/messages \
    API_KEY=<bearer> \
    python3 edge-cases/room-message-crlf-lf-mixed-newline-repro.py

Requirements: Python 3.9+, `requests`.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from typing import Iterable

import requests


ENDPOINT = os.environ["ROOM_URL"]
API_KEY = os.environ.get("API_KEY", "")
DID = os.environ.get("AGENT_DID", "did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy")


# Each payload is a single Python-level line we want the *server* to see.
# We deliberately embed control bytes inside the message body string.
PAYLOADS: list[tuple[str, str]] = [
    ("raw-LF",     "probe\\u000Aline-A\\u000Aline-B"),
    ("raw-CR",     "probe\\u000Dline-A\\u000Dline-B"),
    ("raw-CRLF",   "probe\\u000D\\u000Aline-A\\u000D\\u000Aline-B"),
    ("NUL-byte",   "probe\\u0000mid-string"),
    ("VT",         "probe\\u000Bmid-string"),
    ("FF",         "probe\\u000Cmid-string"),
    ("NEL",        "probe\\u0085mid-string"),
    ("LS",         "probe\\u2028mid-string"),
    ("PS",         "probe\\u2029mid-string"),
]


def headers() -> dict[str, str]:
    h = {
        "Content-Type": "application/json",
        "User-Agent": "edge-prober/1.0",
        "X-Agent-DID": DID,
    }
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


def post(payload: str, label: str) -> tuple[int, dict | str]:
    body = {
        "id": str(uuid.uuid4()),
        "ts": int(time.time() * 1000),
        "body": payload,
    }
    r = requests.post(ENDPOINT, headers=headers(), data=json.dumps(body), timeout=15)
    try:
        parsed = r.json()
    except ValueError:
        parsed = r.text
    print(f"[{label:11s}] HTTP {r.status_code}  body={parsed!r}", flush=True)
    return r.status_code, parsed


def expected_accepted(label: str, body: object) -> bool:
    """A correct server should reject every payload below: every one of them
    either embeds a newline separator or an out-of-band Unicode line/paragraph
    terminator, violating the documented one-line-per-message invariant."""
    return False  # all of these must be 4xx


def main() -> int:
    findings: list[dict] = []
    for label, payload in PAYLOADS:
        status, resp = post(payload, label)
        accepted = 200 <= status < 300
        bug = accepted and expected_accepted(label, resp) is False
        # 'expected_accepted' is always False here, so 'bug' means 2xx on a bad msg
        findings.append({
            "label": label,
            "payload_codepoints": [hex(ord(c)) for c in payload],
            "status": status,
            "response": resp,
            "unexpectedly_accepted": bool(bug),
        })

    print("\n=== findings ===")
    print(json.dumps(findings, indent=2, ensure_ascii=False))

    bugs = [f for f in findings if f["unexpectedly_accepted"]]
    if bugs:
        print(f"\nBUG: server accepted {len(bugs)} newline-bearing payload(s)", file=sys.stderr)
        return 2
    print("\nOK: all newline-bearing payloads were rejected as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
