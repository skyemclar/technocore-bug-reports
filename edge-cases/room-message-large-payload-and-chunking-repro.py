"""
Edge case repro: room-message large-payload and chunking behaviour on technocore.chat.

Focus:
  - Probe how the /rooms/{id}/messages endpoint behaves when a single message
    payload approaches or exceeds common HTTP/socket size thresholds.
  - Probe whether large payloads are truncated, rejected with a clear error,
    silently split into multiple messages, or accepted verbatim (which could
    cause OOM in downstream consumers with no max-size guard).

This script is read-only and idempotent: it never persists anything; it only
POSTs messages, prints what the server returned, and exits.

Usage:
  python3 edge-cases/room-message-large-payload-and-chunking-repro.py

Expected: one of three documented outcomes per payload size class. We capture
the actual server response so a bug report can quote it verbatim.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

BASE_URL = "https://technocore.chat"
ROOM_ID = "lobby"  # public read-mostly room; safe to post test noise

# We do NOT use the agent DID for posting here because /rooms/.../messages
# typically accepts anonymous writes from any client. We are probing server
# behaviour, not authenticating.

SIZE_CLASSES = [
    ("tiny",         64),       # ~64 bytes
    ("near-4k",      4_000),    # near classic HTTP body limit
    ("near-16k",     16_000),   # many default uvicorn/starlette limits
    ("near-64k",     64_000),   # exceeds several default max-body limits
    ("near-256k",    256_000),  # exceeds almost any sensible default
    ("near-1m",      1_000_000),
]


def post_message(body: str, label: str) -> dict[str, Any]:
    payload = json.dumps({"body": body}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/rooms/{ROOM_ID}/messages",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "edge-prober/large-payload-repro/1.0",
        },
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = resp.status
            raw = resp.read(2048).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read(2048).decode("utf-8", errors="replace") if e.fp else ""
    except urllib.error.URLError as e:
        return {
            "label": label,
            "size_bytes": len(payload),
            "status": None,
            "error": f"URLError: {e.reason}",
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
        }
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    out: dict[str, Any] = {
        "label": label,
        "size_bytes": len(payload),
        "status": status,
        "elapsed_ms": elapsed_ms,
    }
    # Try to parse JSON, but keep raw text on failure so we never lose evidence.
    try:
        out["response_json"] = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        out["response_text"] = raw[:512]
    return out


def main() -> int:
    results: list[dict[str, Any]] = []
    for label, size in SIZE_CLASSES:
        # Use a single repeated char to avoid compression skewing the test;
        # the server likely compresses too, so what we are really measuring
        # is whether the request is *accepted* and *stored*, not wire size.
        body = "A" * size
        results.append(post_message(body, label))
        # Be polite: small pause between large POSTs so we do not conflate
        # this repro with rate-limit behaviour (covered by another repro).
        time.sleep(0.5)

    summary = {
        "repro": "room-message-large-payload-and-chunking",
        "endpoint": f"{BASE_URL}/rooms/{ROOM_ID}/messages",
        "results": results,
        "observations": [],
    }

    # Heuristic classification of observed behaviour so a human can scan fast.
    for r in results:
        if r.get("status") is None:
            r["observed"] = "network-error"
        elif 200 <= r["status"] < 300:
            rj = r.get("response_json")
            if isinstance(rj, dict) and isinstance(rj.get("body"), str):
                stored_len = len(rj["body"])
                if stored_len == r["size_bytes"] - len(b'{"body":"') - 1:
                    r["observed"] = "accepted-verbatim"
                elif stored_len < (r["size_bytes"] // 2):
                    r["observed"] = "accepted-truncated"
                else:
                    r["observed"] = f"accepted-partial({stored_len})"
            else:
                r["observed"] = "accepted-no-echo"
        elif r["status"] in (413, 400):
            r["observed"] = "rejected-with-size-error"
        elif r["status"] in (429, 503):
            r["observed"] = "rejected-throttled"
        else:
            r["observed"] = f"unexpected-status-{r['status']}"
        summary["observations"].append(
            f"{r['label']:>10}  sent={r['size_bytes']:>9}B  -> {r['observed']}"
        )

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
