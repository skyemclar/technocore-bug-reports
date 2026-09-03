"""
edge-cases/room-message-empty-payload-repro.py

Focus: probe how the technocore chat server handles a room message whose
payload is *empty* (zero-length body) under various encoding conditions.

The DEVELOPER_POLICY contract states:
    "Keep every message to ONE single line (no newlines), under 4000
    characters, plain text."

It does not explicitly state a *lower* length bound. This script is a
minimal, reproducible black-box probe that documents what we observe
when we POST empty/whitespace-only payloads to the HTTP-native chat
endpoint, so future behavior changes can be diffed against a known
baseline.

Usage:
    python3 room-message-empty-payload-repro.py [base_url]

Default base_url: http://127.0.0.1:8080

The script never assumes a particular success/failure verdict — it
records the raw HTTP status, response headers, and body for each case
so a human can classify the behavior. It also checks our local
preconditions (length cap, no newlines) and reports which of those
hold vs. fail for each probe.

Test cases (all single-line, all under 4000 chars by construction):
    1. empty string body            ""
    2. single space                 " "
    3. only a newline repr char    "\\n"  (JSON escaped, still 1 logical line)
    4. zero-width space (U+200B)    "\u200b"
    5. byte-order mark (U+FEFF)     "\ufeff"
    6. carriage return (U+000D)     "\r"

Each case is sent as a POST to /rooms/<room>/messages with a JSON
envelope that includes a sender DID and the body under test. The
endpoint path mirrors the simplest plausible schema; adjust ROOM_PATH
if your deployment differs.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Tuple

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
ROOM_PATH = "/rooms/general/messages"
SENDER_DID = "did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy"

MAX_LEN = 4000  # upper bound from DEVELOPER_POLICY


def _preconditions(body: str) -> Tuple[bool, bool, list[str]]:
    """Return (len_ok, no_newline, notes)."""
    notes: list[str] = []
    length = len(body)
    len_ok = length <= MAX_LEN
    has_newline = "\n" in body or "\r" in body
    notes.append(f"len={length}")
    notes.append(f"contains_LF={int('\n' in body)}")
    notes.append(f"contains_CR={int('\r' in body)}")
    return len_ok, (not has_newline), notes


def _post(url: str, payload: dict) -> Tuple[int, dict, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            headers_out = dict(resp.getheaders())
            body = resp.read().decode("utf-8", errors="replace")
            return status, headers_out, body
    except urllib.error.HTTPError as e:  # 4xx/5xx with body
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return e.code, dict(e.headers.items()), body
    except urllib.error.URLError as e:
        return 0, {}, f"URLError: {e.reason}"


CASES = [
    ("empty",              ""),
    ("single_space",       " "),
    ("escaped_backslash_n", "\\n"),  # literal backslash + 'n' -> 2 chars, no LF
    ("zwsp_U200B",         "\u200b"),
    ("bom_UFEFF",          "\ufeff"),
    ("cr_U000D",           "\r"),
]


def main() -> int:
    url = BASE_URL.rstrip("/") + ROOM_PATH
    print(f"# probing {url}")
    print(f"# sender={SENDER_DID}")
    rows = []
    for name, body in CASES:
        len_ok, no_newline, notes = _preconditions(body)
        payload = {
            "sender": SENDER_DID,
            "body": body,
            "content_type": "text/plain",
        }
        status, headers, resp_body = _post(url, payload)
        rows.append(
            {
                "case": name,
                "preconditions": {
                    "len_ok": len_ok,
                    "no_newline": no_newline,
                    "notes": notes,
                },
                "http_status": status,
                "response_headers": headers,
                "response_body_preview": resp_body[:200],
            }
        )
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
