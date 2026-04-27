#!/usr/bin/env python3
"""IDAPython script — string extraction.

Reads ``IDA_ANALYSIS_BIN_PATH``, ``IDA_OUTPUT_PATH``, and optionally
``IDA_MIN_LENGTH`` (default 5) from the environment, opens the
database, extracts strings from all segments, and writes a JSON
result.

Result keys match ``StringsResult`` in ``base.py``.
"""

from __future__ import annotations

import json
import os
import sys

try:
    import ida_auto
    import ida_idaapi
    import ida_segment
    import ida_bytes
except ImportError:
    sys.exit("This script must be run inside IDA Pro (idat64 / idal64).")


def _is_printable(data: bytes) -> bool:
    """Return True if all bytes in *data* are printable ASCII."""
    for b in data:
        if b < 0x20 or b > 0x7E:
            return False
    return True


def _scan_ascii_strings(
    start: int, end: int, min_len: int, max_len: int = 4096
) -> list[dict]:
    """Brute-force scan of ASCII strings in [start, end)."""
    found: list[dict] = []
    current_start: int | None = None

    for ea in range(start, end):
        b = ida_bytes.get_byte(ea)
        if 0x20 <= b <= 0x7e:
            if current_start is None:
                current_start = ea
        else:
            if current_start is not None:
                run_len = ea - current_start
                if run_len >= min_len and run_len <= max_len:
                    raw = ida_bytes.get_bytes(current_start, run_len)
                    if raw and _is_printable(raw):
                        found.append({
                            "address": current_start,
                            "value": raw.decode("ascii", errors="replace"),
                            "length": run_len,
                            "type": "ascii",
                        })
                current_start = None

    # trailing run
    if current_start is not None:
        run_len = end - current_start
        if run_len >= min_len and run_len <= max_len:
            raw = ida_bytes.get_bytes(current_start, run_len)
            if raw and _is_printable(raw):
                found.append({
                    "address": current_start,
                    "value": raw.decode("ascii", errors="replace"),
                    "length": run_len,
                    "type": "ascii",
                })

    return found


def _scan_unicode_strings(
    start: int, end: int, min_len: int, max_len: int = 4096
) -> list[dict]:
    """Brute-force scan of UTF-16 (little-endian) strings."""
    found: list[dict] = []
    current_start: int | None = None

    for ea in range(start, end - 1):
        lo = ida_bytes.get_byte(ea)
        hi = ida_bytes.get_byte(ea + 1)
        # printable ASCII in low byte, null high byte => likely UTF-16LE
        if 0x20 <= lo <= 0x7e and hi == 0:
            if current_start is None:
                current_start = ea
        else:
            if current_start is not None:
                run_len_bytes = ea - current_start
                char_count = run_len_bytes // 2
                if char_count >= min_len and run_len_bytes <= max_len:
                    raw = ida_bytes.get_bytes(current_start, run_len_bytes)
                    if raw:
                        try:
                            decoded = raw.decode("utf-16-le", errors="replace")
                        except Exception:
                            decoded = raw.decode("ascii", errors="replace")
                        found.append({
                            "address": current_start,
                            "value": decoded,
                            "length": char_count,
                            "type": "unicode",
                        })
                current_start = None

    return found


def main() -> None:
    bin_path = os.environ.get("IDA_ANALYSIS_BIN_PATH")
    output_path = os.environ.get("IDA_OUTPUT_PATH")
    min_length_str = os.environ.get("IDA_MIN_LENGTH", "5")

    if not bin_path or not output_path:
        sys.exit("ERROR: IDA_ANALYSIS_BIN_PATH and IDA_OUTPUT_PATH must be set.")

    try:
        min_length = int(min_length_str)
    except ValueError:
        min_length = 5

    ida_idaapi.open_database(bin_path, True)
    ida_auto.auto_wait()

    all_strings: list[dict] = []
    seg_qty = ida_segment.get_segm_qty()

    for idx in range(seg_qty):
        seg = ida_segment.getnseg(idx)
        if seg is None:
            continue
        # Skip zero-size segments
        if seg.start_ea >= seg.end_ea:
            continue
        # Scan ASCII then Unicode
        all_strings.extend(
            _scan_ascii_strings(seg.start_ea, seg.end_ea, min_length)
        )
        all_strings.extend(
            _scan_unicode_strings(seg.start_ea, seg.end_ea, min_length)
        )

    # Deduplicate by address
    seen: set[int] = set()
    unique: list[dict] = []
    for s in all_strings:
        if s["address"] not in seen:
            seen.add(s["address"])
            unique.append(s)

    # Sort by address
    unique.sort(key=lambda x: x["address"])

    result: dict = {
        "strings": unique,
        "total_count": len(unique),
        "displayed_count": len(unique),
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    ida_idaapi.close_database(True)


if __name__ == "__main__":
    main()
