"""State and handoff tools for the MCP shared workspace."""

from __future__ import annotations

from pathlib import Path

from server.audit_summaries import state_summary
from server.audited_tool import audited

from datetime import datetime, timezone
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from server.sandbox import Sandbox, SandboxError

HANDOFF_FILES = (
    "PROJECT_STATE.md",
    "PLAN_LOG.md",
    "CHECKPOINTS.md",
    "DECISIONS.md",
)

HandoffFile = Literal[
    "PROJECT_STATE.md",
    "PLAN_LOG.md",
    "CHECKPOINTS.md",
    "DECISIONS.md",
]

MAX_ENTRY_CHARS = 5_000


def append_state_impl(
    sandbox: Sandbox,
    file: str,
    entry: str,
) -> str:
    """Append one bounded entry to an approved handoff file."""
    if file not in HANDOFF_FILES:
        allowed = ", ".join(HANDOFF_FILES)
        raise ValueError(f"Invalid state file {file!r}. " f"Allowed files: {allowed}.")

    if not isinstance(entry, str) or not entry.strip():
        raise ValueError("entry must not be empty.")

    if len(entry) > MAX_ENTRY_CHARS:
        raise ValueError(f"entry exceeds the {MAX_ENTRY_CHARS}-character limit.")

    path = sandbox.resolve(file, for_write=True)

    if not path.exists():
        raise ValueError(
            f"State file {file!r} does not exist. "
            "Create the required handoff files before appending state."
        )

    if not path.is_file():
        raise ValueError(f"State path {file!r} is not a file.")

    # The filename is restricted above, but keep this check explicit.
    if path.name not in HANDOFF_FILES:
        raise SandboxError(f"State file {file!r} is not an approved handoff file.")

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    block = f"\n\n### {timestamp} UTC\n" f"{entry.strip()}\n"

    try:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(block)
    except OSError as exc:
        detail = exc.strerror or "I/O error"
        raise ValueError(f"Cannot append to {file!r}: {detail}.") from None

    return f"Appended {len(entry.strip())} characters " f"to {file}."


APPEND_STATE_DESCRIPTION = (
    "Append a concise handoff entry to one of the four shared state files: "
    "PROJECT_STATE.md, PLAN_LOG.md, CHECKPOINTS.md, or DECISIONS.md. "
    "Use this to record progress, plans, checkpoints, or decisions for "
    "the next agent session. This tool never overwrites existing state."
)


def register(
    mcp: MCPServer,
    sandbox: Sandbox,
    client_id: str = "workspace-client",
    log_path: Path | None = None,
) -> None:
    """Register append_state when the supplied role is authorized."""
    if log_path is None:
        log_path = sandbox.root / ".tool_calls.jsonl"

    @audited(
        tool_name="append_state",
        role=client_id,
        log_path=log_path,
        summarize=state_summary,
    )
    def append_state(
        file: Annotated[
            HandoffFile,
            Field(
                description=(
                    "One of PROJECT_STATE.md, PLAN_LOG.md, "
                    "CHECKPOINTS.md, or DECISIONS.md."
                ),
            ),
        ],
        entry: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_ENTRY_CHARS,
                description=(
                    "Concise information to append for the next " "agent session."
                ),
            ),
        ],
    ) -> str:
        """Append a handoff entry without overwriting existing state."""
        try:
            return append_state_impl(
                sandbox,
                file,
                entry,
            )
        except (SandboxError, ValueError) as exc:
            raise ValueError(str(exc)) from None

    mcp.add_tool(
        append_state,
        name="append_state",
        description=APPEND_STATE_DESCRIPTION,
        structured_output=False,
    )
