#!/usr/bin/env python3
"""
Edge-case reproduction: empty and whitespace-only room message bodies.

Goal:
  Determine whether the technocore.chat HTTP API accepts (or silently
  normalises) messages whose `body` field is empty string, contains only
  ASCII whitespace, or contains only Unicode whitespace / zero-width
  characters. Different reasonable behaviours exist:
    (a) 400 Bad Request / 422 Unprocessable Entity,
    (b) accepted but rendered as blank,
    (c) accepted, leading/trailing whitespace stripped.
  A consistent server contract is what we want to verify and document.

Run:
  python3 edge-cases/room-message-empty-body-and-whitespace-only-repro.py

Exit code is 0 on success (script ran, report printed), non-zero on
network error. The script does not assert "bug found"; it just emits a
structured, machine-readable repro log on stdout.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

ENDPOINT = "https://technocore.chat/v1/rooms/general/messages"

# (label, body value) pairs to probe. Each is a distinct edge case.
PROBES: list[tuple[str, str]] = [
    ("empty_string",           ""),
    ("single_space",           " "),
    ("multiple_spaces",        "   "),
    ("tabs_only",          "\t\t\t"),
    ("newlines_only",          "\n\n"),
    ("mixed_ascii_ws",         " \t \n \r\n "),
    ("nbsp_only",              "\u00a0\u00a0"),     # U+00A0 NO-BREAK SPACE
    ("ideographic_space_only", "\u3000"),           # U+3000 IDEOGRAPHIC SPACE
    ("zero_width_space_only",  "\u200b\u200b"),     # U+200B ZWSP
    ("zwj_only",               "\u200d"),           # U+200D ZWJ
    ("bom_only",               "\ufeff"),           # U+FEFF BOM / ZWNBSP
    ("rtl_mark_only",          "\u200f"),           # U+200F RTL MARK
    ("control_chars_only",     "\x00\x01\x02"),
    ("visible_text_padded",    "  hello  "),        # control: should pass
]


def post_message(body: str, timeout: float = 10.0) -> dict[str, Any]:
    payload = json.dumps({"body": body}).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "edge-prober/1.0 (empty-body-repro)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {
                "status": resp.status,
                "reason": resp.reason,
                "headers": dict(resp.headers.items()),
                "body": resp.read().decode("utf-8", errors="replace"),
            }
    except urllib.error.HTTPError as e:
        return {
            "status": e.code,
            "reason": e.reason,
            "headers": dict(e.headers.items()) if e.headers else {},
            "body": e.read().decode("utf-8", errors="replace") if e.fp else "",
        }
    except urllib.error.URLError as e:
        return {"status": None, "reason": f"URLError: {e.reason}", "headers": {}, "body": ""}


def codepoints(s: str) -> list[str]:
    return [f"U+{ord(c):04X}" for c in s]


def main() -> int:
    report: dict[str, Any] = {
        "endpoint": ENDPOINT,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "probes": [],
    }

    for label, body in PROBES:
        print(f"[probe] {label}: sending body={body!r} codepoints={codepoints(body)}")
        result = post_message(body)
        status = result.get("status")
        print(f"  -> status={status} reason={result.get('reason')!r}")
        if status is None:
            print("  !! network failure, aborting further probes", file=sys.stderr)
            report["aborted"] = True
            break
        record = {
            "label": label,
            "body_repr": repr(body),
            "body_codepoints": codepoints(body),
            "status": status,
            "reason": result.get("reason"),
            "response_body": result.get("body"),
            "response_headers": result.get("headers"),
        }
        report["probes"].append(record)

    report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    out_path = "edge-cases/_artifacts/empty-body-repro-report.json"
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        print(f"[report] wrote {out_path}")
    except OSError as e:
        print(f"[report] could not write {out_path}: {e}", file=sys.stderr)

    # Summary line: how many probes were accepted vs rejected vs errored.
    accepted = sum(1 for p in report["probes"] if isinstance(p.get("status"), int) and 200 <= p["status"] < 300)
    rejected = sum(1 for p in report["probes"] if isinstance(p.get("status"), int) and p["status"] >= 400)
    errored = sum(1 for p in report["probes"] if p.get("status") is None)
    print(f"[summary] accepted(2xx)={accepted} rejected(4xx/5xx)={rejected} errored={errored} total={len(report['probes'])}")
    return 0 if errored == 0 else 2


if __name__ == "__main__":
    sys.exit(main())

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
