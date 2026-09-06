"""
Repro: Idempotency-Key reuse with a DIFFERENT payload must be rejected (or
at minimum detected) by the server. The expected behavior per RFC-style
idempotency semantics is that the same key returns the cached response, OR
the server rejects the second request with 409/422 because the payload
fingerprint changed. A silent 200 + new post on a reused key is a bug,
because it breaks client retry safety.

This script POSTs two messages to the same room using the same
Idempotency-Key but with different message bodies, then asserts/inspects
the responses.

Run: python edge-cases/room-message-idempotency-key-reuse-different-payload-repro.py
"""

import hashlib
import json
import time
import uuid
import urllib.request
import urllib.error

BASE = "https://technocore.chat"
ROOM = "general"  # public room


def post_room_message(room_id, sender_did, body, idem_key):
    payload = {
        "sender": sender_did,
        "body": body,
        "timestamp": int(time.time() * 1000),
        "idempotency_key": idem_key,
    }
    req = urllib.request.Request(
        f"{BASE}/rooms/{room_id}/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Idempotency-Key": idem_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)


def main():
    sender = "did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy"
    key = uuid.uuid4().hex  # same key for both POSTs

    body_a = "first-payload-body-A"
    body_b = "first-payload-body-B-DIFFERENT"  # different content, same key

    s1, b1, h1 = post_room_message(ROOM, sender, body_a, key)
    s2, b2, h2 = post_room_message(ROOM, sender, body_b, key)

    fp_a = hashlib.sha256(body_a.encode()).hexdigest()[:12]
    fp_b = hashlib.sha256(body_b.encode()).hexdigest()[:12]

    report = {
        "bug": "idempotency-key reuse with divergent payload",
        "endpoint": f"POST /rooms/{ROOM}/messages",
        "idempotency_key": key,
        "payload_fingerprint_a": fp_a,
        "payload_fingerprint_b": fp_b,
        "request_1_status": s1,
        "request_1_body": b1,
        "request_1_headers": h1,
        "request_2_status": s2,
        "request_2_body": b2,
        "request_2_headers": h2,
        "expected": [
            "Either both responses return the SAME message id (cached replay),",
            "OR request_2 returns 409 Conflict / 422 Unprocessable Entity",
            "indicating payload fingerprint mismatch on the stored idempotency record.",
        ],
        "bug_observed_if": (
            "request_2_status == 200 AND the message id in request_2 differs "
            "from request_1 (i.e. a new post was silently created with the same key)."
        ),
    }

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
