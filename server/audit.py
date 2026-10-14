"""Security-focused JSONL audit logging for MCP tool calls."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

_AUDIT_LOCK = Lock()
AUDIT_MAX_BYTES = 10 * 1024 * 1024
AUDIT_BACKUP_COUNT = 5


def _rotate_if_needed(log_path: Path, incoming_bytes: int) -> None:
    """Rotate one process's JSONL log before it exceeds its size limit."""
    if not log_path.exists() or log_path.stat().st_size + incoming_bytes <= AUDIT_MAX_BYTES:
        return

    oldest = log_path.with_name(f"{log_path.name}.{AUDIT_BACKUP_COUNT}")
    oldest.unlink(missing_ok=True)

    for index in range(AUDIT_BACKUP_COUNT - 1, 0, -1):
        source = log_path.with_name(f"{log_path.name}.{index}")
        if source.exists():
            source.replace(log_path.with_name(f"{log_path.name}.{index + 1}"))

    log_path.replace(log_path.with_name(f"{log_path.name}.1"))


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
        return {str(key): _safe_value(item) for key, item in list(value.items())[:20]}

    return str(value)[:200]


def audit_tool_call(
    log_path: Path,
    *,
    tool: str,
    client: str,
    success: bool,
    arguments: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Append one sanitized tool-call record to the JSONL audit log."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": tool,
        "client": client,
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

    encoded_line = (line + "\n").encode("utf-8")

    with _AUDIT_LOCK:
        _rotate_if_needed(log_path, len(encoded_line))
        with log_path.open("ab") as handle:
            handle.write(encoded_line)
            handle.flush()
            os.fsync(handle.fileno())
