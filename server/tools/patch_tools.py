"""Exact-context unified-diff application for sandboxed workspace files."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from server.audited_tool import audited
from server.config import MAX_WRITE_BYTES
from server.sandbox import Sandbox
from server.tools.write_tools import _FILE_WRITE_LOCK

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


def apply_patch_impl(
    sandbox: Sandbox,
    patch: str,
    expected_hash: str | None = None,
    expected_hashes: dict[str, str] | None = None,
) -> str:
    """Apply exact-context modifications with optional SHA-256 concurrency guards."""
    parsed = _parse_patch(patch)
    paths = [relative for relative, _ in parsed]
    if expected_hash is not None and len(paths) != 1:
        raise ValueError("expected_hash is supported only for a single-file patch; use expected_hashes for multiple files.")
    if expected_hash is not None:
        expected_hashes = {paths[0]: expected_hash}
    if expected_hashes is not None and set(expected_hashes) != set(paths):
        raise ValueError("When supplied, expected_hashes must contain exactly one SHA-256 hash for every patched path.")

    staged: list[tuple[Path, Path, Path]] = []
    prepared: list[tuple[Path, str, bytes]] = []
    with _FILE_WRITE_LOCK:
        try:
            for relative, hunks in parsed:
                target = sandbox.resolve(relative, for_write=True)
                if target.is_symlink() or not target.is_file():
                    raise ValueError(f"Patch target must be an existing regular file: {relative!r}.")
                current_bytes = target.read_bytes()
                if expected_hashes is not None:
                    expected = expected_hashes[relative]
                    if not isinstance(expected, str) or len(expected) != 64:
                        raise ValueError(f"expected hash for {relative!r} must be a 64-character SHA-256 hex digest.")
                    try:
                        int(expected, 16)
                    except ValueError:
                        raise ValueError(f"expected hash for {relative!r} must be a 64-character SHA-256 hex digest.") from None
                    actual = hashlib.sha256(current_bytes).hexdigest()
                    if actual.lower() != expected.lower():
                        raise ValueError(
                            f"Concurrency conflict for {relative}: expected hash does not match current file content. "
                            f"Current SHA-256: {actual}. Read the latest file and retry."
                        )
                try:
                    current = current_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    raise ValueError(f"Patch target is not UTF-8 text: {relative!r}.") from None
                updated = _apply_hunks(current, hunks, relative)
                if len(updated.encode("utf-8")) > MAX_WRITE_BYTES:
                    raise ValueError(f"Patched file exceeds the {MAX_WRITE_BYTES:,}-byte limit: {relative!r}.")
                prepared.append((target, updated, current_bytes))

            # Stage new contents and recoverable originals before touching targets.
            for target, updated, original_bytes in prepared:
                fd, temp_name = tempfile.mkstemp(prefix=".mcp-patch-new-", dir=target.parent)
                temp = Path(temp_name)
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                    stream.write(updated)
                    stream.flush()
                    os.fsync(stream.fileno())
                backup_fd, backup_name = tempfile.mkstemp(prefix=".mcp-patch-backup-", dir=target.parent)
                backup = Path(backup_name)
                with os.fdopen(backup_fd, "wb") as stream:
                    stream.write(original_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
                backup.chmod(target.stat().st_mode & 0o7777)
                staged.append((target, temp, backup))

            try:
                for target, temp, _backup in staged:
                    os.replace(temp, target)
            except Exception:
                rollback_errors = []
                for target, _temp, backup in reversed(staged):
                    try:
                        if backup.exists():
                            os.replace(backup, target)
                    except OSError as rollback_error:
                        rollback_errors.append(str(rollback_error))
                if rollback_errors:
                    raise RuntimeError("Patch failed and rollback was incomplete: " + "; ".join(rollback_errors))
                raise
        except Exception:
            for _target, temp, backup in staged:
                for artifact in (temp, backup):
                    try:
                        artifact.unlink(missing_ok=True)
                    except OSError:
                        pass
            raise
        else:
            for _target, _temp, backup in staged:
                backup.unlink(missing_ok=True)
    return "Applied transactional exact-context patch to: " + ", ".join(sandbox.relative(p) for p, _, _ in prepared)


def register(mcp: MCPServer, sandbox: Sandbox, client_id: str = "workspace-client", log_path: Path | None = None) -> None:
    if log_path is None:
        log_path = sandbox.root / ".tool_calls.jsonl"

    @audited(tool_name="apply_patch", role=client_id, log_path=log_path,
             summarize=lambda _a, kw: {"patch_chars": len(kw.get("patch", ""))})
    def apply_patch(
        patch: Annotated[str, Field(min_length=1, max_length=_MAX_PATCH_CHARS, description="Unified diff with exact context; only existing files may be modified.")],
        expected_hash: str | None = Field(default=None, description="SHA-256 of the current file bytes; for single-file patches only."),
        expected_hashes: dict[str, str] | None = Field(default=None, description="Optional mapping of every patched workspace-relative path to its current SHA-256 hash; required keys must exactly match patched paths."),
    ) -> str:
        """Apply an exact-context unified diff with optional optimistic concurrency checks."""
        return apply_patch_impl(sandbox, patch, expected_hash, expected_hashes)

    mcp.add_tool(apply_patch, name="apply_patch", structured_output=False)
