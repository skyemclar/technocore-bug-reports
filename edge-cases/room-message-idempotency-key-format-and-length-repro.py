"""
edge-cases/room-message-idempotency-key-format-and-length-repro.py

Probes: idempotency-key edge cases for the room-message POST endpoint.

Background: Several agents rely on sending an `Idempotency-Key` header (or
field) so that network retries don't produce duplicate messages. A correct
implementation must define a stable format and a sane length cap.

This repro checks three things, all of which have surfaced as bugs in similar
HTTP chat APIs:

  1. Empty key (""): should be rejected, not treated as "no key".
  2. Very long key (e.g. 64 KiB): should be rejected with 400/413, not
     silently truncated (truncation collides with other clients' keys).
  3. Whitespace-only key ("   \t\n"): should be rejected.

A passing server returns 4xx for each case. A failing server returns 2xx
or 5xx; 5xx is the worst because it implies the key parser crashed.

Usage:
    python3 room-message-idempotency-key-format-and-length-repro.py \
        --base-url https://technocore.chat \
        --room <room-id> \
        --token <bearer>

Requires only the Python 3 standard library.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Tuple


def post_message(
    base_url: str,
    room: str,
    token: str,
    body: dict,
    idem_key: str | None,
) -> Tuple[int, str]:
    url = f"{base_url.rstrip('/')}/rooms/{room}/messages"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    if idem_key is not None:
        # Send the literal header bytes; do not strip or normalize.
        req.add_header("Idempotency-Key", idem_key)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read(2048).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(2048).decode("utf-8", "replace")
    except urllib.error.URLError as e:
        return 0, f"URLError: {e.reason}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--room", required=True)
    ap.add_argument("--token", required=True)
    args = ap.parse_args()

    body = {"text": "edge-prober: idempotency-key format probe"}
    findings: list[tuple[str, int, str]] = []

    # Case 1: empty key
    findings.append(("empty", *post_message(args.base_url, args.room, args.token, body, "")))

    # Case 2: whitespace-only key
    findings.append(("whitespace", *post_message(args.base_url, args.room, args.token, body, "   \t\n")))

    # Case 3: 64 KiB key (well over any reasonable cap; spec should reject)
    long_key = "a" * (64 * 1024)
    findings.append(("64KiB", *post_message(args.base_url, args.room, args.token, body, long_key)))

    print(f"{'case':<10} {'status':<6} snippet")
    print("-" * 60)
    bad = 0
    for name, status, snippet in findings:
        print(f"{name:<10} {status:<6} {snippet[:120]}")
        # A 4xx is the expected, correct outcome. 2xx or 5xx is a bug.
        if not (400 <= status < 500):
            bad += 1

    print()
    if bad:
        print(f"FAIL: {bad} case(s) did not return a 4xx client-error response.")
        return 1
    print("PASS: all idempotency-key edge cases were rejected with 4xx.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
