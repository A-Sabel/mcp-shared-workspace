"""Workspace file, state, and audit-log management tools."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from server.audited_tool import audited
from server.sandbox import HANDOFF_FILES, Sandbox, SandboxError

STATE_LIMIT = 128_000
AUDIT_LIMIT = 200
AUDIT_RESPONSE_LIMIT = 64 * 1024


def _summary(_args, kwargs):
    return {k: v for k, v in kwargs.items() if k in {"source", "destination", "path", "file", "limit", "offset", "tool", "success"}}


def _reject_symlink_components(root: Path, relative_path: str) -> None:
    """Reject symlinks in the requested lexical path, including the final component."""
    relative = Path(relative_path)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise SandboxError("Symbolic links are not supported by this operation.")


def _state_path(sandbox: Sandbox, name: str) -> Path:
    if name not in HANDOFF_FILES:
        raise ValueError(f"file must be one of: {', '.join(HANDOFF_FILES)}.")
    path = sandbox.resolve(name)
    _reject_symlink_components(sandbox.root, name)
    return path


def _atomic_write(path: Path, content: str) -> None:
    encoded = content.encode("utf-8")
    if len(encoded) > STATE_LIMIT:
        raise ValueError(f"State content exceeds the {STATE_LIMIT}-byte limit.")
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _archive_current(sandbox: Sandbox, name: str, path: Path) -> Path:
    if not path.exists():
        raise ValueError(f"{name} does not exist; nothing to archive.")
    if path.stat().st_size > STATE_LIMIT:
        raise ValueError("State file exceeds the 128 KB safety limit.")
    content = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    _reject_symlink_components(sandbox.root, ".workspace-archive")
    archive_dir = sandbox.resolve(".workspace-archive", for_write=True)
    archive_dir.mkdir(mode=0o700, exist_ok=True)
    archive = archive_dir / f"{name}.{digest}.md"
    # Identical content is archived only once, even if the operation is retried.
    if not archive.exists():
        temp = archive.with_name(f".{archive.name}.{os.getpid()}.tmp")
        try:
            with temp.open("x", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp, archive)
            except FileExistsError:
                pass
        finally:
            temp.unlink(missing_ok=True)
    return archive


def _entries(content: str) -> list[str]:
    lines = content.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("### ")]
    if not starts:
        return [content] if content.strip() else []
    prefix = lines[:starts[0]]
    result = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        block = lines[start:end]
        if index == 0 and prefix:
            block = prefix + block
        value = "\n".join(block).strip()
        if value:
            result.append(value)
    return result


def register(mcp: MCPServer, sandbox: Sandbox, log_path: Path) -> None:
    @audited(tool_name="move_file", role="workspace-client", log_path=log_path, summarize=_summary)
    def move_file(
        source: Annotated[str, Field(min_length=1, max_length=512, description="Workspace-relative source file.")],
        destination: Annotated[str, Field(min_length=1, max_length=512, description="Workspace-relative destination path.")],
        overwrite: Annotated[bool, Field(description="Allow replacing an existing regular file; defaults to false.")] = False,
    ) -> str:
        """Move or rename a regular file within the workspace without overwriting by default."""
        src = sandbox.resolve(source, for_write=True)
        dst = sandbox.resolve(destination, for_write=True)
        _reject_symlink_components(sandbox.root, source)
        _reject_symlink_components(sandbox.root, destination)
        if not src.is_file() or src.is_symlink():
            raise ValueError("Source must be an existing regular file.")
        if dst.exists():
            if not overwrite:
                raise ValueError("Destination already exists; set overwrite=true to replace a regular file.")
            if not dst.is_file() or dst.is_symlink():
                raise ValueError("Only an existing regular file can be overwritten.")
        if src == dst:
            raise ValueError("Source and destination are identical.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
        return f"Moved {source!r} to {destination!r}."

    @audited(tool_name="create_directory", role="workspace-client", log_path=log_path, summarize=_summary)
    def create_directory(
        path: Annotated[str, Field(min_length=1, max_length=512, description="Workspace-relative directory path.")],
        exist_ok: Annotated[bool, Field(description="Succeed if the directory already exists.")] = True,
    ) -> str:
        """Create a directory and any missing parents inside the workspace."""
        target = sandbox.resolve(path, for_write=True)
        _reject_symlink_components(sandbox.root, path)
        if target.exists() and not target.is_dir():
            raise ValueError("A non-directory already exists at the requested path.")
        target.mkdir(parents=True, exist_ok=exist_ok)
        return f"Directory ready: {path!r}."

    @audited(tool_name="read_state", role="workspace-client", log_path=log_path, summarize=_summary)
    def read_state(
        file: Annotated[str, Field(description="One of PROJECT_STATE.md, PLAN_LOG.md, CHECKPOINTS.md, or DECISIONS.md.")],
        limit: Annotated[int, Field(ge=1, le=100, description="Maximum recent entries to return.")] = 10,
        offset: Annotated[int, Field(ge=0, le=10000, description="Skip this many entries from the newest.")] = 0,
        section: Annotated[str | None, Field(description="Optional exact Markdown heading to select.")] = None,
    ) -> str:
        """Read bounded recent entries from an approved shared state file."""
        path = _state_path(sandbox, file)
        if not path.exists():
            return f"{file} does not exist."
        if path.stat().st_size > STATE_LIMIT:
            raise ValueError("State file exceeds the 128 KB safety limit.")
        content = path.read_text(encoding="utf-8")
        if section:
            lines = content.splitlines()
            heading = f"## {section}".casefold()
            start = next((i for i, line in enumerate(lines) if line.casefold() == heading), None)
            if start is None:
                raise ValueError(f"Section {section!r} was not found.")
            end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
            content = "\n".join(lines[start:end])
        else:
            entries = _entries(content)
            selected = list(reversed(entries))[offset:offset + limit]
            content = "\n\n".join(reversed(selected))
        return content or f"{file} is empty."

    @audited(tool_name="archive_state", role="workspace-client", log_path=log_path, summarize=_summary)
    def archive_state(
        file: Annotated[str, Field(description="Approved shared state filename.")],
    ) -> str:
        """Create an immutable, content-addressed archive copy without changing active state."""
        path = _state_path(sandbox, file)
        archive = _archive_current(sandbox, file, path)
        return f"Archived {file} to {sandbox.relative(archive)!r}."

    @audited(tool_name="compact_state", role="workspace-client", log_path=log_path, summarize=_summary)
    def compact_state(
        file: Annotated[str, Field(description="Approved shared state filename.")],
        summary: Annotated[str, Field(min_length=1, max_length=30000, description="Agent-prepared replacement state; history is archived first.")],
    ) -> str:
        """Archive the complete current state, then atomically replace it with an agent-provided summary."""
        path = _state_path(sandbox, file)
        if not path.exists():
            raise ValueError(f"{file} does not exist; create it with append_state first.")
        archive = _archive_current(sandbox, file, path)
        replacement = summary.rstrip() + "\n"
        _atomic_write(path, replacement)
        return f"Compacted {file}; full prior contents preserved at {sandbox.relative(archive)!r}."

    @audited(tool_name="read_audit_log", role="workspace-client", log_path=log_path, summarize=_summary)
    def read_audit_log(
        limit: Annotated[int, Field(ge=1, le=AUDIT_LIMIT, description="Maximum records to return.")] = 50,
        offset: Annotated[int, Field(ge=0, le=10000, description="Skip records from newest to oldest.")] = 0,
        tool: Annotated[str | None, Field(description="Optional exact tool-name filter.")] = None,
        success: Annotated[bool | None, Field(description="Optional success/failure filter.")] = None,
    ) -> str:
        """Read bounded, read-only recent JSONL audit records."""
        if not log_path.exists():
            return "Audit log does not exist."
        records = []
        try:
            # Read only a bounded tail; a single truncated first line is discarded.
            with log_path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                end = handle.tell()
                start = max(0, end - 1_000_000)
                handle.seek(start)
                raw = handle.read(1_000_000)
            text = raw.decode("utf-8", errors="replace")
            lines = text.splitlines()
            if start and lines:
                lines = lines[1:]
            for line in lines:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                if tool is not None and record.get("tool") != tool:
                    continue
                if success is not None and record.get("success") is not success:
                    continue
                records.append(record)
        except OSError:
            raise ValueError("Audit log could not be read.") from None
        selected = list(reversed(records))[offset:offset + limit]
        output = json.dumps(selected, ensure_ascii=False, indent=2)
        if len(output.encode("utf-8")) > AUDIT_RESPONSE_LIMIT:
            raise ValueError("Selected audit records exceed the 64 KB response limit; reduce limit.")
        return output if selected else "No matching audit records."

    for handler, name in (
        (move_file, "move_file"),
        (create_directory, "create_directory"),
        (read_state, "read_state"),
        (archive_state, "archive_state"),
        (compact_state, "compact_state"),
        (read_audit_log, "read_audit_log"),
    ):
        mcp.add_tool(handler, name=name, structured_output=False)
