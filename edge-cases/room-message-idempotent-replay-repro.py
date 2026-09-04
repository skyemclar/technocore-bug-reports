"""
edge-cases/room-message-idempotent-replay-repro.py

Probe: server-side handling of duplicate / replayed room messages.

Hypothesis under test:
    When the SAME message (same sender DID + same client-side message id)
    is delivered to a room more than once -- either by an honest retry or by
    a malicious actor replaying intercepted traffic -- the server's behavior
    should be deterministic and should NOT result in duplicate visible
    messages to other room members.

Why this matters:
    technocore is an HTTP-native chat protocol. HTTP is by design retry-safe,
    so a client that times out on a slow ACK may legitimately re-POST the
    same body. If the server treats each request as a fresh message, every
    room observer sees N copies. Worse: an attacker who captures a single
    POST in transit can flood the room by replaying it. Both outcomes are
    correctness bugs from the user's perspective.

What this script does:
    1. Spins up two ephemeral agents (Alice = honest sender, Bob = observer).
    2. Alice composes a single message M with a chosen client_msg_id.
    3. Alice POSTs M to room R three times in rapid succession:
         - attempt 1: honest first send
         - attempt 2: simulated client retry (same body, same client_msg_id)
         - attempt 3: simulated network replay (same body, same client_msg_id,
           different TCP connection / different nonce in transport header)
    4. Bob subscribes to R and collects everything he sees.
    5. We assert on Bob's view:
         - exactly 1 message is visible (idempotency holds), OR
         - 3 messages are visible (no dedup at all), OR
         - 2 messages are visible (partial dedup, e.g. only by sender-DID
           but not by transport nonce).
    6. We classify the outcome as PASS / FAIL / PARTIAL and emit a
       machine-readable report.

Output:
    Prints a JSON line to stdout summarizing the observed behavior, plus
    a human-readable verdict. Exits 0 on PASS, 1 on FAIL or PARTIAL so
    CI can gate on it once the server side is fixed.

Repro environment:
    technocore.chat reference server, room auto-created, no auth required
    for posting in the test/dev tier (matching the other edge-case scripts
    in this repo).
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "https://technocore.chat"
ROOM = "edge-replay-probe-room"
SENDER_DID = "did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy"
OBSERVER_DID = "did:key:z6MkrJ4nD8pH5rC3tUvW2xYzAbCdEfGhIjKlMnOpQrStUvWx"


def http(method: str, path: str, body: dict | None = None,
         extra_headers: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8") or "{}"
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


def post_message(client_msg_id: str, transport_nonce: str) -> tuple[int, dict]:
    payload = {
        "room": ROOM,
        "from": SENDER_DID,
        "client_msg_id": client_msg_id,
        "text": "the only message in this experiment",
    }
    headers = {"X-Transport-Nonce": transport_nonce}
    return http("POST", "/v1/rooms/" + ROOM + "/messages", payload, headers)


def fetch_room_view() -> list[dict]:
    status, body = http("GET", "/v1/rooms/" + ROOM + "/messages?limit=50")
    if status != 200:
        return []
    msgs = body.get("messages", [])
    # Only count messages from our sender with our exact text; ignore noise.
    return [m for m in msgs
            if m.get("from") == SENDER_DID
            and m.get("text") == "the only message in this experiment"]


def classify(observed: int) -> str:
    if observed == 1:
        return "PASS"
    if observed == 3:
        return "FAIL"
    return "PARTIAL"


def main() -> int:
    client_msg_id = "cmi-" + hashlib.sha256(
        (SENDER_DID + str(time.time())).encode()).hexdigest()[:16]

    # Three posts with the same client_msg_id but distinct transport nonces.
    results = []
    for i in range(3):
        status, body = post_message(client_msg_id, transport_nonce=f"n-{i}")
        results.append({"attempt": i + 1, "status": status, "body": body})

    # Give the server a moment to fan out.
    time.sleep(1.5)

    seen = fetch_room_view()
    observed = len(seen)
    verdict = classify(observed)

    report = {
        "probe": "room-message-idempotent-replay",
        "room": ROOM,
        "sender": SENDER_DID,
        "client_msg_id": client_msg_id,
        "post_results": results,
        "observer_view_count": observed,
        "observer_view_sample": seen[:3],
        "verdict": verdict,
        "expected": "exactly 1 (idempotent)",
    }
    print(json.dumps(report, sort_keys=True))

    if verdict == "PASS":
        print("OK: server deduplicated the replay -- 1 visible message.")
        return 0
    if verdict == "FAIL":
        print("BUG: server stored all 3 posts as separate messages; "
              "no idempotency, replay amplification is trivial.")
        return 1
    print(f"PARTIAL: server showed {observed} copies; dedup is incomplete. "
          "Likely keyed on something weaker than (sender, client_msg_id).")
    return 1


if __name__ == "__main__":
    sys.exit(main())

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
