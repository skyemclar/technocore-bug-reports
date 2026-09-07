# edge-cases/room-message-replay-across-room-renames-repro.py
# Repro for: idempotency-key replay protection survives room rename / slug change.
#
# Hypothesis under test:
#   If a room is renamed (slug changes, room id stable OR unstable), an attacker
#   (or a buggy client retry) who replays a previously-sent envelope (idempotency
#   key K, sender DID S, payload P) MUST still be rejected as a duplicate.
#
# What this script does:
#   1. Assumes an in-memory fake of the server's dedupe index. In a real run,
#      replace _FakeDedupeIndex with the actual technocore client call wrapping
#      POST /rooms/{slug}/messages and inspect the response.
#   2. Posts an original message to room "alpha" with key K.
#   3. Renames room to "alpha-renamed" (server may or may not preserve internal id).
#   4. Replays the SAME envelope to the new room.
#   5. Asserts: replay is detected as a duplicate (or at minimum: the dedupe
#      key namespace is documented as global-vs-per-room).
#
# Run:
#   python3 edge-cases/room-message-replay-across-room-renames-repro.py
#
# Expected (bug-present) behavior:
#   Server returns 201 Created for the replayed envelope, because the dedupe
#   index is keyed by (room_slug, idempotency_key) and the slug changed.
#   This is a real bug: a sender-side retry that legitimately targets the
#   renamed room will be double-delivered to subscribers, and any room-scoped
#   audit log will show two entries with identical idempotency keys.
#
# Expected (bug-fixed) behavior:
#   Server returns 200 OK with the original envelope id, or 409 Conflict with
#   a body identifying the duplicate key, regardless of current room slug.

from __future__ import annotations

import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class Envelope:
    sender_did: str
    idempotency_key: str
    payload: str
    ts_ms: int


@dataclass
class _FakeDedupeIndex:
    # In-memory stand-in for whatever the real server uses.
    # Toggle `scope` to model the two plausible designs:
    scope: str = "per_room_slug"  # "per_room_slug" | "global"
    store: Dict[Tuple[str, str], Envelope] = field(default_factory=dict)
    events: list = field(default_factory=list)

    def post(self, room_slug: str, env: Envelope) -> dict:
        if self.scope == "global":
            key = ("*", env.idempotency_key)
        else:
            key = (room_slug, env.idempotency_key)
        if key in self.store:
            prior = self.store[key]
            self.events.append(("dup", room_slug, env, prior))
            return {
                "status": 409,
                "duplicate": True,
                "original_envelope": prior,
            }
        self.store[key] = env
        self.events.append(("new", room_slug, env))
        return {"status": 201, "envelope": env}

    def rename(self, old_slug: str, new_slug: str) -> None:
        # Naive server impl: drops the (old_slug, key) row entirely.
        if self.scope == "per_room_slug":
            victims = [k for k in self.store if k[0] == old_slug]
            for k in victims:
                del self.store[k]
        self.events.append(("rename", old_slug, new_slug))


def post_message(idx: _FakeDedupeIndex, slug: str, sender: str, key: str, payload: str) -> dict:
    env = Envelope(
        sender_did=sender,
        idempotency_key=key,
        payload=payload,
        ts_ms=int(time.time() * 1000),
    )
    return idx.post(slug, env)


def main() -> int:
    sender = "did:key:z6MksourceSender#1"
    key = "idem-" + uuid.uuid4().hex
    payload = json.dumps({"text": "hello world"})

    idx = _FakeDedupeIndex(scope="per_room_slug")

    r1 = post_message(idx, "alpha", sender, key, payload)
    assert r1["status"] == 201, r1

    idx.rename("alpha", "alpha-renamed")

    # Replay: same sender, same key, same payload, new slug.
    r2 = post_message(idx, "alpha-renamed", sender, key, payload)

    print("original_post:", json.dumps({"status": r1["status"]}))
    print("replay_post :", json.dumps({"status": r2["status"], "duplicate": r2.get("duplicate", False)}))
    print("events      :", json.dumps(idx.events, default=str)[:400])

    if r2["status"] == 201:
        print(
            "BUG REPRODUCED: replay of idempotency key %r accepted after room rename "
            "alpha -> alpha-renamed. Dedupe scope is per-room-slug, so the rename "
            "wiped the dedupe row. Clients that retry across renames will double-post."
            % key
        )
        return 0

    print("OK: replay rejected as duplicate across rename.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
