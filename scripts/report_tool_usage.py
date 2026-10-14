"""Summarize content-free MCP result telemetry from JSONL audit logs."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _new_totals() -> dict[str, int]:
    return defaultdict(int)


def summarize(paths: list[Path]) -> dict[str, Any]:
    tools: dict[str, dict[str, int]] = defaultdict(_new_totals)
    records = malformed = 0
    for path in paths:
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                if not isinstance(record, dict):
                    malformed += 1
                    continue
                name = str(record.get("tool", "unknown"))
                item = tools[name]
                item["calls"] += 1
                item["successes"] += bool(record.get("success"))
                item["failures"] += not bool(record.get("success"))
                result = record.get("result")
                if not isinstance(result, dict):
                    result = {}
                item["result_bytes"] += int(result.get("bytes") or 0)
                item["result_chars"] += int(result.get("chars") or 0)
                read_ranges = result.get("read_ranges", [])
                if not isinstance(read_ranges, list):
                    read_ranges = []
                for read_range in read_ranges:
                    if not isinstance(read_range, dict):
                        continue
                    item["read_chunks"] += 1
                    start = read_range.get("start_line")
                    end = read_range.get("end_line")
                    if isinstance(start, int) and isinstance(end, int):
                        item["returned_lines"] += max(0, end - start + 1)
                    item["chunks_with_more"] += bool(read_range.get("has_more"))
                records += 1
    return {
        "records": records,
        "malformed_lines": malformed,
        "files": [str(path) for path in paths if path.is_file()],
        "tools": {name: dict(values) for name, values in sorted(tools.items())},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Audit JSONL path (rotated siblings are included); defaults to logs/tool_calls.jsonl.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a table.")
    args = parser.parse_args()

    base = args.log_file or (PROJECT_ROOT / "logs" / "tool_calls.jsonl")
    paths = sorted(base.parent.glob(base.name + "*"))
    report = summarize(paths)
    if args.json:
        print(json.dumps(report, indent=2))
        return

    print(f"Audit records: {report['records']}  |  malformed lines: {report['malformed_lines']}")
    if not report["tools"]:
        print("No telemetry records found. Restart the MCP server to enable result metrics.")
        return
    print("tool                 calls  ok  fail  result bytes  read chunks  lines  more")
    for name, values in report["tools"].items():
        print(
            f"{name:20} {values.get('calls', 0):5} {values.get('successes', 0):3} "
            f"{values.get('failures', 0):5} {values.get('result_bytes', 0):12} "
            f"{values.get('read_chunks', 0):11} {values.get('returned_lines', 0):6} "
            f"{values.get('chunks_with_more', 0):5}"
        )
    print("\nResult bytes are server output size, not model-token counts.")


if __name__ == "__main__":
    main()
