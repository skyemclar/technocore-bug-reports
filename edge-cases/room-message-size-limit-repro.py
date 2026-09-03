#!/usr/bin/env python3
"""
Reproducer for technocore.chat room message size boundary behavior.

Focus: What happens when a message approaches, meets, and exceeds the
documented transport / per-message cap? We probe with valid UTF-8 at
various sizes and capture the server's response shape so we can file a
proper, reproducible bug report if behavior is inconsistent.

Usage:
    python3 edge-cases/room-message-size-limit-repro.py \
        --host technocore.chat --port 80 --room lobby \
        --sizes 1024,4096,8192,16384,32768,65535,65536,65537

Notes:
  - This script only reads and prints; it does not POST secrets or
    trigger any payment flow (there is no such system on technocore).
  - Wire format assumed: HTTP POST with text/plain body, X-Room header
    and X-DID header carrying an Ed25519 did:key identifier.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from typing import List, Optional


DEFAULT_SIZES = [1024, 4096, 8192, 16384, 32768, 65535, 65536, 65537, 131072]


@dataclass
class ProbeResult:
    size: int
    status: Optional[int]
    reason: Optional[str]
    body_len: int
    elapsed_ms: int
    error: Optional[str]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def build_body(target_size: int) -> bytes:
    # Valid UTF-8 payload; pad with ASCII 'A' (0x41). We avoid surrogates.
    if target_size <= 0:
        return b""
    return (b"A" * (target_size - 1)) + b"\n"


def post_once(host: str, port: int, room: str, did: str, body: bytes,
              timeout: float) -> ProbeResult:
    url = f"http://{host}:{port}/rooms/{room}/messages"
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "text/plain; charset=utf-8",
            "X-Room": room,
            "X-DID": did,
            "Content-Length": str(len(body)),
        },
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            elapsed = int((time.monotonic() - started) * 1000)
            return ProbeResult(
                size=len(body),
                status=resp.status,
                reason=resp.reason,
                body_len=len(data),
                elapsed_ms=elapsed,
                error=None,
            )
    except urllib.error.HTTPError as e:
        elapsed = int((time.monotonic() - started) * 1000)
        return ProbeResult(
            size=len(body),
            status=e.code,
            reason=getattr(e, "reason", None),
            body_len=len(e.read() or b""),
            elapsed_ms=elapsed,
            error=None,
        )
    except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
        elapsed = int((time.monotonic() - started) * 1000)
        return ProbeResult(
            size=len(body),
            status=None,
            reason=None,
            body_len=0,
            elapsed_ms=elapsed,
            error=f"{type(e).__name__}: {e}",
        )


def run(host: str, port: int, room: str, did: str, sizes: List[int],
        timeout: float) -> List[ProbeResult]:
    results: List[ProbeResult] = []
    for s in sizes:
        body = build_body(s)
        r = post_once(host, port, room, did, body, timeout)
        results.append(r)
        # Be polite: small delay between probes so we don't get rate-limited
        # by accident while testing.
        time.sleep(0.1)
    return results


def render_table(results: List[ProbeResult]) -> str:
    header = f"{'size':>8} {'status':>7} {'reason':<14} {'body':>6} {'ms':>5}  error"
    line = "-" * len(header)
    rows = [header, line]
    for r in results:
        rows.append(
            f"{r.size:>8} {str(r.status):>7} {str(r.reason or ''):<14} "
            f"{r.body_len:>6} {r.elapsed_ms:>5}  {r.error or ''}"
        )
    return "\n".join(rows)


def main(argv: List[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="technocore.chat")
    p.add_argument("--port", type=int, default=80)
    p.add_argument("--room", default="lobby")
    p.add_argument("--did", default="did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy")
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--sizes", default=",".join(str(s) for s in DEFAULT_SIZES),
                   help="Comma-separated byte sizes to probe")
    args = p.parse_args(argv)

    sizes = sorted({int(x) for x in args.sizes.split(",") if x.strip()})
    results = run(args.host, args.port, args.room, args.did, sizes, args.timeout)
    print(render_table(results))
    print()
    print("JSON:")
    print(json.dumps([asdict(r) for r in results], indent=2))

    # Heuristic: flag inconsistencies between adjacent sizes, e.g. a 65535
    # success followed by a 65536 rejection vs. both succeeding vs. both
    # being dropped silently with no status.
    flagged = []
    prev: Optional[ProbeResult] = None
    for r in results:
        if prev is not None:
            if (prev.status in (200, 201)) != (r.status in (200, 201)):
                flagged.append((prev.size, r.size))
        prev = r
    if flagged:
        print()
        print("Boundary transitions detected between sizes:", flagged)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
