"""Write-oriented tools for the MCP shared workspace."""

from pathlib import Path

from server.audit_summaries import (
    path_summary,
    replace_summary,
    write_summary,
)
from server.audited_tool import audited

from mcp.server.mcpserver import MCPServer
from pydantic import Field

import shutil

from server.config import MAX_WRITE_BYTES
from server.sandbox import Sandbox, SandboxError

MAX_REPLACE_TEXT_CHARS = 50_000
MAX_REPLACEMENTS = 100


def _validate_text(value: str, name: str, max_chars: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string.")

    if not value:
        raise ValueError(f"{name} must not be empty.")

    if len(value) > max_chars:
        raise ValueError(f"{name} exceeds the {max_chars:,}-character limit.")

    return value


def write_file_impl(
    sandbox: Sandbox,
    path: str,
    content: str,
) -> str:
    """Create or overwrite one file inside the sandbox."""
    if not isinstance(content, str):
        raise ValueError("content must be a string.")

    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        raise ValueError(f"content exceeds the {MAX_WRITE_BYTES:,}-byte limit.")

    target = sandbox.resolve(path, for_write=True)

    if target.exists() and not target.is_file():
        raise ValueError(f"Target is not a regular file: {path}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    return (
        f"Wrote {sandbox.relative(target)} "
        f"({len(content.encode('utf-8')):,} bytes)."
    )


def str_replace_impl(
    sandbox: Sandbox,
    path: str,
    old: str,
    new: str,
    replace_all: bool = False,
) -> str:
    """Replace exact text inside one sandbox file."""
    _validate_text(old, "old", MAX_REPLACE_TEXT_CHARS)

    if not isinstance(new, str):
        raise ValueError("new must be a string.")

    if len(new) > MAX_REPLACE_TEXT_CHARS:
        raise ValueError(f"new exceeds the {MAX_REPLACE_TEXT_CHARS:,}-character limit.")

    target = sandbox.resolve(path, for_write=True)

    if not target.exists():
        raise ValueError(f"File does not exist: {path}")

    if not target.is_file():
        raise ValueError(f"Target is not a regular file: {path}")

    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"File is not valid UTF-8 text: {path}") from exc

    occurrences = text.count(old)

    if occurrences == 0:
        raise ValueError(f"Text to replace was not found in {path}.")

    if not replace_all and occurrences > 1:
        raise ValueError(
            f"Found {occurrences} occurrences in {path}. "
            "Set replace_all=true or provide a more specific match."
        )

    replacements = occurrences if replace_all else 1
    updated = text.replace(
        old,
        new,
        -1 if replace_all else 1,
    )

    if len(updated.encode("utf-8")) > MAX_WRITE_BYTES:
        raise ValueError(f"Updated file exceeds the {MAX_WRITE_BYTES:,}-byte limit.")

    target.write_text(updated, encoding="utf-8")

    return f"Replaced {replacements} occurrence(s) in " f"{sandbox.relative(target)}."


def delete_file_impl(
    sandbox: Sandbox,
    path: str,
) -> str:
    """Move one regular file into the sandbox trash directory."""
    target = sandbox.resolve(path, for_write=True)

    if not target.exists():
        raise ValueError(f"File does not exist: {path}")

    if not target.is_file():
        raise ValueError(f"delete_file only accepts regular files: {path}")

    relative = target.relative_to(sandbox.root)
    trash_root = sandbox.root / ".trash"
    trash_target = trash_root / relative

    trash_target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if trash_target.exists():
        stem = trash_target.stem
        suffix = trash_target.suffix
        counter = 1

        while True:
            candidate = trash_target.parent / f"{stem}~{counter}{suffix}"

            if not candidate.exists():
                trash_target = candidate
                break

            counter += 1

    shutil.move(
        str(target),
        str(trash_target),
    )

    return (
        f"Moved {sandbox.relative(target)} to trash as "
        f"{sandbox.relative(trash_target)}."
    )


WRITE_FILE_DESCRIPTION = """
Create or overwrite one UTF-8 text file inside the workspace.

Use this when a file needs to be created or its complete contents need to be
replaced. The path must remain inside the sandbox and protected paths such as
.git and environment/credential files are rejected. Prefer str_replace for a
small targeted edit so unnecessary file contents do not need to be rewritten.
""".strip()


STR_REPLACE_DESCRIPTION = """
Replace exact text inside an existing UTF-8 text file.

Use this for small, targeted modifications. By default the old text must occur
exactly once; if it occurs multiple times, the tool fails instead of making an
ambiguous edit. Set replace_all=true only when replacing every occurrence is
intentional. The updated file remains subject to the workspace size limit.
""".strip()


DELETE_FILE_DESCRIPTION = """
Delete one regular file inside the workspace.

Use this only when the requested file should actually be removed. Paths are
validated against the sandbox and protected locations cannot be deleted.
Directories cannot be deleted through this tool.
""".strip()


def register(
    mcp: MCPServer,
    sandbox: Sandbox,
    client_id: str = "workspace-client",
    log_path: Path | None = None,
) -> None:
    """Register the workspace write tools."""
    if log_path is None:
        log_path = sandbox.root / ".tool_calls.jsonl"

    @mcp.tool(
        name="write_file",
        description=WRITE_FILE_DESCRIPTION,
    )
    @audited(
        tool_name="write_file",
        role=client_id,
        log_path=log_path,
        summarize=write_summary,
    )
    def write_file(
        path: str = Field(description="Workspace-relative file path."),
        content: str = Field(description="Complete UTF-8 text content to write."),
    ) -> str:
        return write_file_impl(sandbox, path, content)

    @mcp.tool(
        name="str_replace",
        description=STR_REPLACE_DESCRIPTION,
    )
    @audited(
        tool_name="str_replace",
        role=client_id,
        log_path=log_path,
        summarize=replace_summary,
    )
    def str_replace(
        path: str = Field(description="Workspace-relative file path."),
        old: str = Field(description="Exact text that must be replaced."),
        new: str = Field(description="Replacement text."),
        replace_all: bool = Field(
            default=False,
            description="Replace every occurrence.",
        ),
    ) -> str:
        return str_replace_impl(
            sandbox,
            path,
            old,
            new,
            replace_all,
        )

    @mcp.tool(
        name="delete_file",
        description=DELETE_FILE_DESCRIPTION,
    )
    @audited(
        tool_name="delete_file",
        role=client_id,
        log_path=log_path,
        summarize=path_summary,
    )
    def delete_file(
        path: str = Field(description="Workspace-relative file path."),
    ) -> str:
        return delete_file_impl(sandbox, path)
