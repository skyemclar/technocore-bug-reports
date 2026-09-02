#!/usr/bin/env python3
"""
edge-cases/room-join-empty-id-repro.py

Probes how the technocore.chat HTTP API handles a POST to /v1/rooms/join
when the `room_id` field is supplied as the empty string, missing entirely,
or set to whitespace-only.

Observed behavior across multiple clients suggests the server is inconsistent
in its 400-class validation here: some clients report a clean 400 with a
machine-readable error code, others get a 500 with a stack-leaking body.
This script reproduces the three variants and prints what the server returned,
so maintainers can confirm the canonical response.

Usage:
    python3 room-join-empty-id-repro.py [base_url]

Default base_url: http://localhost:8080

Expected (per spec, https://technocore.chat/docs#join):
  - empty / missing / whitespace room_id  -> 400 with body
        {"error": "invalid_room_id", "message": "..."}
  - never 500, never echoes raw stack trace

No auth is used; this is for a local dev server. If your instance requires
a DID bearer token, set $TECHNOCORE_TOKEN in the environment and the script
will attach it as `Authorization: Bearer <token>`.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


CASES: list[tuple[str, dict[str, Any]]] = [
    ("empty_string", {"room_id": ""}),
    ("whitespace_only", {"room_id": "   "}),
    ("field_missing", {}),
    ("null_value", {"room_id": None}),
    ("non_string_int", {"room_id": 42}),
]


def post_join(base_url: str, body: dict[str, Any]) -> tuple[int, str, str]:
    raw = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/v1/rooms/join",
        data=raw,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    token = os.environ.get("TECHNOCORE_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), ""
    except urllib.error.URLError as e:
        return 0, "", f"URLError: {e.reason}"
    except Exception as e:  # noqa: BLE001 - we want to surface the raw text
        return 0, "", f"{type(e).__name__}: {e}"


def looks_like_stack_trace(body: str) -> bool:
    if not body:
        return False
    markers = ("Traceback (most recent call last):", "at ", "Exception:",
               ".java:", ".py", "Exception in thread")
    return any(m in body for m in markers)


def main(argv: list[str]) -> int:
    base = argv[1] if len(argv) > 1 else "http://localhost:8080"
    print(f"probing {base}/v1/rooms/join with {len(CASES)} edge cases\n")

    failures = 0
    for label, body in CASES:
        status, text, err = post_join(base, body)
        print(f"--- {label} ---")
        print(f"  request body : {json.dumps(body)}")
        if err:
            print(f"  transport err: {err}")
            failures += 1
            continue
        print(f"  status       : {status}")
        snippet = text[:240].replace("\n", " ")
        print(f"  body (first 240 chars): {snippet}")

        if status == 500:
            print("  FAIL: server returned 500 for client-side validation error")
            failures += 1
        elif looks_like_stack_trace(text):
            print("  FAIL: response body appears to leak a stack trace")
            failures += 1
        elif status >= 400:
            try:
                parsed = json.loads(text)
                if "error" not in parsed:
                    print("  FAIL: 4xx response missing machine-readable 'error' field")
                    failures += 1
            except json.JSONDecodeError:
                print("  FAIL: 4xx response is not valid JSON")
                failures += 1

    print()
    if failures:
        print(f"{failures} failure(s) detected against expected contract")
        return 1
    print("all edge cases matched the documented contract")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
