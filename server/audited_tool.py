"""Helpers for adding audit logging to MCP tool handlers."""

from collections.abc import Callable, Collection
from functools import wraps
from pathlib import Path
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from server.audit import audit_tool_call
from server.security.request_identity import current_audit_identity


def audited(
    *,
    tool_name: str,
    role: str | Collection[str],
    log_path: Path,
    summarize: Callable[[tuple[Any, ...], dict[str, Any]], dict[str, Any]],
    summarize_result: Callable[[Any], dict[str, Any]] | None = None,
):
    """Audit an MCP tool handler without logging sensitive payloads."""
    audit_role = role if isinstance(role, str) else "+".join(sorted(role))

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)

                result_metrics: dict[str, Any] = {}
                if isinstance(result, str):
                    result_metrics["bytes"] = len(result.encode("utf-8"))
                    result_metrics["chars"] = len(result)
                elif isinstance(result, bytes):
                    result_metrics["bytes"] = len(result)
                if summarize_result is not None:
                    try:
                        result_metrics.update(summarize_result(result))
                    except Exception:
                        # Telemetry must not change a successful tool result.
                        pass

                audit_tool_call(
                    log_path,
                    tool=tool_name,
                    client=current_audit_identity(audit_role),
                    success=True,
                    arguments=summarize(args, kwargs),
                    result=result_metrics or None,
                )

                return result

            except Exception as exc:
                try:
                    safe_arguments = summarize(args, kwargs)
                except Exception:
                    safe_arguments = {}

                audit_tool_call(
                    log_path,
                    tool=tool_name,
                    client=current_audit_identity(audit_role),
                    success=False,
                    arguments=safe_arguments,
                    error=str(exc),
                )

                raise ToolError(str(exc)) from None

        return wrapper

    return decorator
