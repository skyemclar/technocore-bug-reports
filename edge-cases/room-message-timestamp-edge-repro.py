#!/usr/bin/env python3
"""
Reproduction script for room message timestamp edge cases in technocore protocol.
Tests: zero epoch, negative, unix epoch boundary, and extreme timestamp values.
"""

import json
import time
import struct


def make_message(content: str, timestamp: int) -> dict:
    """Craft a message dict with a specific timestamp."""
    return {
        "type": "room.message",
        "room": "test-room",
        "content": content,
        "timestamp": timestamp,
        "sender": "did:key:test",
        "id": f"msg-{timestamp}"
    }


def pack_varint(value: int) -> bytes:
    """Pack an integer as a variable-length integer (protobuf-style)."""
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def main():
    test_cases = []

    # Case 1: Unix epoch zero (1970-01-01 00:00:00 UTC)
    ts_zero = 0
    msg_zero = make_message("epoch zero message", ts_zero)
    test_cases.append(("epoch_zero", ts_zero, msg_zero))

    # Case 2: Negative timestamp (before epoch)
    ts_negative = -1
    msg_negative = make_message("negative timestamp message", ts_negative)
    test_cases.append(("negative_timestamp", ts_negative, msg_negative))

    # Case 3: Year 2038 problem boundary (INT_MAX for 32-bit signed)
    ts_2038 = 2147483647  # 2038-01-19 03:14:07 UTC
    msg_2038 = make_message("32-bit int max timestamp", ts_2038)
    test_cases.append(("int32_max_boundary", ts_2038, msg_2038))

    # Case 4: Milliseconds instead of seconds (off-by-1000)
    ts_ms = int(time.time() * 1000)
    msg_ms = make_message("millisecond timestamp", ts_ms)
    test_cases.append(("millisecond_vs_second", ts_ms, msg_ms))

    # Case 5: Microseconds (off-by-1000000)
    ts_us = int(time.time() * 1000000)
    msg_us = make_message("microsecond timestamp", ts_us)
    test_cases.append(("microsecond_vs_second", ts_us, msg_us))

    # Case 6: Very large timestamp (year 10000+)
    ts_huge = 253402300700  # 9999-12-31 23:59:59
    msg_huge = make_message("far future timestamp", ts_huge)
    test_cases.append(("far_future_timestamp", ts_huge, msg_huge))

    # Case 7: Zero-width timestamp (potential division issues)
    ts_inf = float('inf')
    msg_inf = make_message("infinity timestamp", int(ts_inf))
    test_cases.append(("infinity_timestamp", ts_inf, msg_inf))

    # Case 8: NaN timestamp
    ts_nan = float('nan')
    try:
        msg_nan = make_message("NaN timestamp", int(ts_nan))
    except ValueError:
        msg_nan = {"error": "NaN cannot be converted to int", "original": ts_nan}
    test_cases.append(("nan_timestamp", ts_nan, msg_nan))

    # Serialize for inspection
    output = {
        "description": "Room message timestamp edge cases",
        "protocol_note": "Timestamps should be Unix seconds (int64). Reject or clamp extremes.",
        "test_cases": [
            {
                "name": name,
                "input_timestamp": ts,
                "message": msg,
                "packed_varint": pack_varint(int(ts)).hex() if isinstance(ts, (int, float)) and ts == ts else None,
                "risk": get_risk(name)
            }
            for name, ts, msg in test_cases
        ]
    }

    print(json.dumps(output, indent=2))


def get_risk(name: str) -> str:
    risks = {
        "epoch_zero": "Likely accepted; may sort before all other messages",
        "negative_timestamp": "Bug: negative timestamps should be rejected",
        "int32_max_boundary": "Bug: 32-bit parsers may overflow or misinterpret",
        "millisecond_vs_second": "Bug: 1000x inflation causes future-dating",
        "microsecond_vs_second": "Bug: 1000000x inflation causes future-dating",
        "far_future_timestamp": "May exceed storage schema limits (int32)",
        "infinity_timestamp": "Bug: varint packing will fail or loop",
        "nan_timestamp": "Bug: NaN is invalid for timestamp field"
    }
    return risks.get(name, "unknown")


if __name__ == "__main__":
    main()

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
