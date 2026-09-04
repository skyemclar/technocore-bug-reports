"""
edge-cases/room-message-idempotency-dedupe-repro.py

Probes whether technocore.chat deduplicates identical room messages sent in
rapid succession (same DID + same payload, no client-generated message id).

Observed in the wild: chat-style protocols often *don't* dedupe, leading to
echo spam; some *do* dedupe aggressively, leading to legitimate re-sends
being swallowed after transient network failures. Either extreme is a bug.

This script reproduces both scenarios against a local technocore instance
(default http://127.0.0.1:8080) by:
  1. Posting an identical signed envelope 5 times within ~50 ms.
  2. Polling the room GET endpoint for ~2 s.
  3. Reporting the resulting message set so the maintainer can decide
     whether the dedupe policy is intentional.

Run:
    python3 edge-cases/room-message-idempotency-dedupe-repro.py \
        --room <room_id> --did <did:key:...> --count 5

Expected (sane) behaviour: N >= 1 and N <= count, with the *first* copy
preserved. BUG A: N == 0 (server silently swallowed a fresh post).
BUG B: N == count (no dedupe at all; spammable).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE = "http://127.0.0.1:8080"


def _http(method: str, url: str, body: bytes | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b""
    except urllib.error.URLError as e:
        print(f"[fatal] network error contacting {url}: {e}", file=sys.stderr)
        sys.exit(2)


def post_message(base: str, room: str, did: str, payload: dict[str, Any]) -> int:
    body = json.dumps({"did": did, "payload": payload}).encode()
    status, _ = _http("POST", f"{base}/rooms/{room}/messages", body)
    return status


def list_messages(base: str, room: str) -> list[dict[str, Any]]:
    status, raw = _http("GET", f"{base}/rooms/{room}/messages")
    if status != 200:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data.get("messages", []) if isinstance(data, dict) else data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--room", required=True)
    ap.add_argument("--did", required=True, help="signer DID, e.g. did:key:z6Mk...")
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--payload", default="idempotency-probe")
    args = ap.parse_args()

    payload = {"text": args.payload, "ts": int(time.time() * 1000)}

    print(f"[info] posting {args.count} identical envelopes to room={args.room}")
    statuses: list[int] = []
    t0 = time.monotonic()
    for i in range(args.count):
        statuses.append(post_message(args.base, args.room, args.did, payload))
    elapsed_ms = (time.monotonic() - t0) * 1000
    print(f"[info] POST statuses={statuses} elapsed={elapsed_ms:.1f}ms")

    time.sleep(2.0)  # allow any async fan-out to settle
    msgs = list_messages(args.base, args.room)
    matches = [m for m in msgs if m.get("payload", {}).get("text") == args.payload]

    print(f"[result] stored copies matching payload: {len(matches)}")
    for m in matches[:10]:
        print(f"   - id={m.get('id')} ts={m.get('ts')} did={m.get('did')}")

    if 1 <= len(matches) <= args.count:
        print("[verdict] OK: bounded dedupe (1 <= N <= count)")
        return 0
    if len(matches) == 0:
        print("[verdict] BUG A: fresh post was silently dropped (N == 0)")
        return 1
    if len(matches) > args.count:
        print(f"[verdict] BUG B: no dedupe, server amplified input (N={len(matches)} > count={args.count})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
