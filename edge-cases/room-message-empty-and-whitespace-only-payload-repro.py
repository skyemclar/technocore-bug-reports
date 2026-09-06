"""
Repro for: server-side handling of empty / whitespace-only / zero-width room messages.

Hypothesis (bug): The /rooms/{room}/messages POST handler accepts messages whose
"text" field is empty, contains only ASCII whitespace, or contains only Unicode
"zero-width" / format characters (ZWSP, ZWNJ, ZWJ, BOM, joiners, bidi marks),
and persists them as visible posts, allocates message IDs, and triggers delivery /
notification side effects. This pollutes room history, defeats rate limiting
(by inflating message counts with free noise), and can be used to grief rooms
or fingerprint bot presence.

Repro:

    pip install httpx
    python edge-cases/room-message-empty-and-whitespace-only-payload-repro.py \
        --base https://technocore.chat \
        --room <room-id> \
        --token <bearer>

Expected (post-fix) behavior: server normalizes/strips zero-width + bidi format
characters, trims ASCII whitespace, and rejects (400) any payload whose visible
glyph count is zero, without consuming rate-limit budget or allocating an ID.

The script is read-only against a real room; it sends small synthetic payloads
and reports the server's response code + the message ID echoed back, if any.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid

import httpx

# Each tuple: (label, payload_text)
# Payloads exercise distinct normalization paths the server may or may not apply.
CASES: list[tuple[str, str]] = [
    ("empty_string",           ""),
    ("single_space",           " "),
    ("multiple_spaces",        "   "),
    ("tabs_and_newlines",      "\t\n\r  \n\t"),
    ("zero_width_space",       "\u200b"),
    ("zwj_only",               "\u200d\u200d\u200d"),
    ("zwnj_only",              "\u200c\u200c"),
    ("word_joiner_only",       "\u2060\u2060\u2060"),
    ("bom_only",               "\ufeff"),
    ("bidi_marks_only",        "\u200e\u200f\u202a\u202c"),
    ("mixed_zw_plus_spaces",   "  \u200b \u200c \t \ufeff "),
    ("zw_wrapped_visible_a",   "\u200ba\u200b"),   # a visible, but only if strip is done
    ("bidi_isolate_lonely",    "\u2068\u2069"),
]


def post_message(client: httpx.Client, base: str, room: str, token: str,
                 text: str, idempotency_key: str) -> httpx.Response:
    url = f"{base.rstrip('/')}/rooms/{room}/messages"
    body = {
        "idempotency_key": idempotency_key,
        "text": text,
        "content_type": "text/plain",
    }
    return client.post(
        url,
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="https://technocore.chat")
    ap.add_argument("--room", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--dry", action="store_true",
                    help="Print requests instead of sending (for triage).")
    args = ap.parse_args()

    findings: list[dict] = []
    with httpx.Client() as client:
        for label, text in CASES:
            idem = f"probe-empty-{label}-{uuid.uuid4().hex[:12]}"
            if args.dry:
                print(json.dumps({"label": label, "text": text, "idem": idem}))
                continue
            try:
                r = post_message(client, args.base, args.room, args.token, text, idem)
            except httpx.HTTPError as e:
                findings.append({"label": label, "error": repr(e)})
                time.sleep(0.2)
                continue
            row = {
                "label": label,
                "text_repr": repr(text),
                "status": r.status_code,
                "id": r.headers.get("X-Message-Id")
                     or r.json().get("id") if r.headers.get("content-type", "").startswith("application/json") else None,
            }
            try:
                row["body"] = r.json()
            except Exception:
                row["body_text"] = r.text[:200]
            findings.append(row)
            time.sleep(0.25)  # be polite

    report = {
        "probed_at": int(time.time()),
        "base": args.base,
        "room": args.room,
        "findings": findings,
        "interpretation": (
            "Any case with status 2xx AND a returned message id is a likely bug: "
            "empty/whitespace/zero-width-only payloads should be rejected (400) "
            "or normalized to empty and rejected, not stored and broadcast."
        ),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
