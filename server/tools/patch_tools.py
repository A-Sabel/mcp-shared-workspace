"""Exact-context unified-diff application for sandboxed workspace files."""

from __future__ import annotations

import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from server.audited_tool import audited
from server.config import MAX_WRITE_BYTES
from server.sandbox import Sandbox

_PATCH_LOCK = threading.RLock()
_MAX_PATCH_CHARS = 100_000
_MAX_PATCH_FILES = 20
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$")


def _parse_patch(patch: str) -> list[tuple[str, list[tuple[str, list[str], list[str]]]]]:
    if not isinstance(patch, str) or not patch or len(patch) > _MAX_PATCH_CHARS:
        raise ValueError(f"patch must be non-empty and at most {_MAX_PATCH_CHARS:,} characters.")
    lines = patch.splitlines()
    files = []
    i = 0
    while i < len(lines):
        if not lines[i].startswith("--- "):
            raise ValueError(f"Expected '---' file header at patch line {i + 1}.")
        old_name = lines[i][4:].split("\t", 1)[0]
        i += 1
        if i >= len(lines) or not lines[i].startswith("+++ "):
            raise ValueError("Each patch file requires a '+++' header.")
        new_name = lines[i][4:].split("\t", 1)[0]
        i += 1
        if old_name == "/dev/null" or new_name == "/dev/null":
            raise ValueError("File creation and deletion patches are not supported; use write_file or delete_file.")
        old_path = old_name[2:] if old_name.startswith("a/") else old_name
        new_path = new_name[2:] if new_name.startswith("b/") else new_name
        if old_path != new_path:
            raise ValueError("Renames are not supported by apply_patch.")
        hunks = []
        while i < len(lines) and not lines[i].startswith("--- "):
            if not lines[i].startswith("@@ "):
                if not lines[i].strip():
                    i += 1
                    continue
                raise ValueError(f"Expected hunk header at patch line {i + 1}.")
            match = _HUNK.match(lines[i])
            if not match:
                raise ValueError(f"Invalid hunk header at patch line {i + 1}.")
            i += 1
            old_lines, new_lines = [], []
            while i < len(lines) and not lines[i].startswith("@@ ") and not lines[i].startswith("--- "):
                line = lines[i]
                if line.startswith("\\ No newline"):
                    i += 1
                    continue
                if not line or line[0] not in " +-":
                    raise ValueError(f"Invalid hunk line at patch line {i + 1}.")
                if line[0] in " -":
                    old_lines.append(line[1:])
                if line[0] in " +":
                    new_lines.append(line[1:])
                i += 1
            old_count = int(match.group(2) or "1")
            new_count = int(match.group(4) or "1")
            if len(old_lines) != old_count or len(new_lines) != new_count:
                raise ValueError("Hunk line counts do not match the hunk header.")
            hunks.append((match.group(1), old_lines, new_lines))
        if not hunks:
            raise ValueError(f"No hunks found for {old_path!r}.")
        files.append((old_path, hunks))
        if len(files) > _MAX_PATCH_FILES:
            raise ValueError(f"Patch exceeds the {_MAX_PATCH_FILES}-file limit.")
    if not files:
        raise ValueError("Patch contains no file changes.")
    if len({path for path, _ in files}) != len(files):
        raise ValueError("Patch contains duplicate file paths.")
    return files


def _apply_hunks(original: str, hunks: list[tuple[str, list[str], list[str]]], path: str) -> str:
    source = original.splitlines(keepends=True)
    output: list[str] = []
    cursor = 0
    for line_number, old_lines, new_lines in hunks:
        start = max(0, int(line_number) - 1)
        if start < cursor or start > len(source):
            raise ValueError(f"Overlapping or out-of-range hunk for {path!r}.")
        output.extend(source[cursor:start])
        actual = [line.rstrip("\r\n") for line in source[start:start + len(old_lines)]]
        if actual != old_lines:
            raise ValueError(f"Exact context mismatch in {path!r} near line {line_number}; no files were changed.")
        output.extend(line + "\n" for line in new_lines)
        cursor = start + len(old_lines)
    output.extend(source[cursor:])
    return "".join(output)


def apply_patch_impl(sandbox: Sandbox, patch: str) -> str:
    """Apply exact-context modifications after validating every target; each file replacement is atomic."""
    parsed = _parse_patch(patch)
    prepared: list[tuple[Path, str]] = []
    for relative, hunks in parsed:
        target = sandbox.resolve(relative, for_write=True)
        if target.is_symlink() or not target.is_file():
            raise ValueError(f"Patch target must be an existing regular file: {relative!r}.")
        try:
            current = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ValueError(f"Patch target is not UTF-8 text: {relative!r}.") from None
        updated = _apply_hunks(current, hunks, relative)
        if len(updated.encode("utf-8")) > MAX_WRITE_BYTES:
            raise ValueError(f"Patched file exceeds the {MAX_WRITE_BYTES:,}-byte limit: {relative!r}.")
        prepared.append((target, updated))

    staged: list[tuple[Path, Path]] = []
    with _PATCH_LOCK:
        try:
            # Prepare all replacements before swapping any target.
            for target, updated in prepared:
                fd, temp_name = tempfile.mkstemp(prefix=".mcp-patch-", dir=target.parent)
                temp = Path(temp_name)
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                    stream.write(updated)
                    stream.flush()
                    os.fsync(stream.fileno())
                staged.append((target, temp))
            for target, temp in staged:
                os.replace(temp, target)
        except Exception:
            for _, temp in staged:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
    return "Applied exact-context patch to: " + ", ".join(sandbox.relative(p) for p, _ in prepared)


def register(mcp: MCPServer, sandbox: Sandbox, client_id: str = "workspace-client", log_path: Path | None = None) -> None:
    if log_path is None:
        log_path = sandbox.root / ".tool_calls.jsonl"

    @audited(tool_name="apply_patch", role=client_id, log_path=log_path,
             summarize=lambda _a, kw: {"patch_chars": len(kw.get("patch", ""))})
    def apply_patch(
        patch: Annotated[str, Field(min_length=1, max_length=_MAX_PATCH_CHARS, description="Unified diff with exact context; only existing files may be modified.")],
    ) -> str:
        """Apply an exact-context unified diff to existing workspace files atomically."""
        return apply_patch_impl(sandbox, patch)

    mcp.add_tool(apply_patch, name="apply_patch", structured_output=False)
