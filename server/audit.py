"""Security-focused JSONL audit logging for MCP tool calls."""

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


_AUDIT_LOCK = Lock()


def _safe_value(value: Any) -> Any:
    """Convert a value into safe, bounded audit metadata."""
    if isinstance(value, str):
        if len(value) > 200:
            return value[:200] + "...[truncated]"
        return value

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value[:20]]

    if isinstance(value, dict):
        return {
            str(key): _safe_value(item)
            for key, item in list(value.items())[:20]
        }

    return str(value)[:200]


def audit_tool_call(
    log_path: Path,
    *,
    tool: str,
    role: str,
    success: bool,
    arguments: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Append one sanitized tool-call record to the JSONL audit log."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "tool": tool,
        "role": role,
        "success": success,
    }

    if arguments:
        record["arguments"] = _safe_value(arguments)

    if error:
        record["error"] = _safe_value(error)

    log_path.parent.mkdir(parents=True, exist_ok=True)

    line = json.dumps(
        record,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    with _AUDIT_LOCK:
        with log_path.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(line + "\n")