"""Write-oriented tools for the MCP shared workspace."""

import json
import os
import shutil
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from server.audit_summaries import (
    path_summary,
    replace_summary,
    write_summary,
)
from server.audited_tool import audited

from mcp.server.mcpserver import MCPServer
from pydantic import Field

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
    """Move one regular file into uniquely identified workspace trash."""
    target = sandbox.resolve(path, for_write=True)
    _reject_symlink_path(sandbox, path)
    if not os.path.lexists(target):
        raise ValueError(f"File does not exist: {path}")
    if not stat.S_ISREG(target.lstat().st_mode):
        raise ValueError(f"delete_file only accepts regular files: {path}")

    original_path = sandbox.relative(target)
    entry_dir, trash_path = _new_trash_entry("file", original_path, sandbox)
    try:
        target.rename(entry_dir / "payload")
    except OSError as exc:
        shutil.rmtree(entry_dir, ignore_errors=True)
        detail = exc.strerror or "I/O error"
        raise ValueError(f"Could not move {path!r} to workspace trash: {detail}.") from None
    return _json_result(
        original_path=original_path,
        trash_path=trash_path,
        message="File moved to workspace trash; use restore_file with trash_path to restore it.",
    )


def restore_file_impl(sandbox: Sandbox, trash_path: str) -> str:
    """Restore a soft-deleted file without replacing an existing path."""
    entry_dir, payload, metadata_path, canonical_trash_path = _trash_entry_from_path(
        sandbox, trash_path
    )
    metadata = _load_trash_metadata(metadata_path, expected_kind="file")
    if metadata.get("trash_path") != canonical_trash_path:
        raise ValueError("Trash metadata does not match the selected trash path.")
    original_path = metadata.get("original_path")
    if not isinstance(original_path, str) or not original_path:
        raise ValueError("Trash metadata does not contain a valid original path.")

    _reject_symlink_path(sandbox, original_path)
    destination = sandbox.resolve(original_path, for_write=True)
    if not stat.S_ISREG(payload.lstat().st_mode):
        raise ValueError("The selected trash entry is not a regular file.")
    if os.path.lexists(destination):
        raise ValueError(
            f"Cannot restore {original_path!r}: a file or directory already exists there."
        )
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        detail = exc.strerror or "I/O error"
        raise ValueError(f"Could not prepare the restore destination: {detail}.") from None
    _reject_symlink_path(sandbox, original_path)
    destination = sandbox.resolve(original_path, for_write=True)
    try:
        # Atomic creation fails if another path appears after the conflict check.
        os.link(payload, destination, follow_symlinks=False)
    except FileExistsError:
        raise ValueError(
            f"Cannot restore {original_path!r}: a file or directory already exists there."
        ) from None
    except OSError as exc:
        detail = exc.strerror or "I/O error"
        raise ValueError(f"Could not restore {original_path!r}: {detail}.") from None

    cleanup_warnings: list[str] = []
    try:
        payload.unlink()
    except OSError:
        cleanup_warnings.append("The restored file also remains in workspace trash.")
    try:
        metadata_path.unlink()
        entry_dir.rmdir()
    except OSError:
        cleanup_warnings.append("A stale trash metadata entry remains and may be cleaned later.")
    result = dict(
        original_path=original_path,
        trash_path=canonical_trash_path,
        message="File restored to its original workspace path.",
    )
    if cleanup_warnings:
        result["warning"] = " ".join(cleanup_warnings)
    return _json_result(**result)


def remove_directory_impl(sandbox: Sandbox, path: str) -> str:
    """Remove an empty workspace directory without recursing."""
    target = sandbox.resolve(path, for_write=True)
    _reject_symlink_path(sandbox, path)
    if not os.path.lexists(target):
        raise ValueError(f"Directory does not exist: {path}")
    if not target.is_dir():
        raise ValueError(f"Path is not a directory: {path}")
    try:
        next(target.iterdir())
    except StopIteration:
        pass
    except OSError as exc:
        detail = exc.strerror or "I/O error"
        raise ValueError(f"Could not inspect directory {path!r}: {detail}.") from None
    else:
        raise ValueError(
            f"Directory {path!r} is not empty; remove or move its contents explicitly first."
        )
    try:
        target.rmdir()
    except OSError as exc:
        detail = exc.strerror or "I/O error"
        raise ValueError(f"Could not remove empty directory {path!r}: {detail}.") from None
    return _json_result(path=sandbox.relative(target), removed=True)


def _reject_symlink_path(sandbox: Sandbox, path: str) -> None:
    """Reject symlinks and junctions in a mutation path, including the leaf."""
    lexical = Path(os.path.abspath(sandbox.root / path))
    try:
        parts = lexical.relative_to(sandbox.root).parts
    except ValueError:
        raise SandboxError(f"Path {path!r} is outside the workspace.") from None
    current = sandbox.root
    for part in parts:
        current = current / part
        is_junction = getattr(current, "is_junction", lambda: False)
        if current.is_symlink() or is_junction():
            raise ValueError(
                f"Symlinks and junctions are not allowed for this operation: {path!r}."
            )


def _ensure_trash_root(sandbox: Sandbox) -> Path:
    trash_root = sandbox.trash_dir
    is_junction = getattr(trash_root, "is_junction", lambda: False)
    if trash_root.is_symlink() or is_junction():
        raise ValueError("Workspace trash cannot be a symlink or junction.")
    if os.path.lexists(trash_root) and not trash_root.is_dir():
        raise ValueError("Workspace trash path is not a directory.")
    try:
        trash_root.mkdir(mode=0o700, exist_ok=True)
    except OSError as exc:
        detail = exc.strerror or "I/O error"
        raise ValueError(f"Could not prepare workspace trash: {detail}.") from None
    return trash_root


def _new_trash_entry(kind: str, original_path: str, sandbox: Sandbox) -> tuple[Path, str]:
    trash_root = _ensure_trash_root(sandbox)
    while True:
        entry_dir = trash_root / str(uuid.uuid4())
        try:
            entry_dir.mkdir(mode=0o700)
            break
        except FileExistsError:
            continue
        except OSError as exc:
            detail = exc.strerror or "I/O error"
            raise ValueError(f"Could not create a workspace trash entry: {detail}.") from None
    payload = entry_dir / "payload"
    metadata = {
        "version": 1,
        "kind": kind,
        "original_path": original_path,
        "trash_path": sandbox.relative(payload),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        (entry_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    except OSError as exc:
        entry_dir.rmdir()
        detail = exc.strerror or "I/O error"
        raise ValueError(f"Could not create workspace trash metadata: {detail}.") from None
    return entry_dir, sandbox.relative(payload)


def _trash_entry_from_path(
    sandbox: Sandbox, trash_path: str
) -> tuple[Path, Path, Path, str]:
    if not isinstance(trash_path, str):
        raise ValueError("trash_path must be a string returned by delete_file.")
    parts = PurePosixPath(trash_path).parts
    if len(parts) != 3 or parts[0] != ".trash" or parts[2] != "payload":
        raise ValueError("trash_path must identify a payload returned by delete_file.")
    try:
        entry_id = str(uuid.UUID(parts[1]))
    except (ValueError, AttributeError):
        raise ValueError("trash_path contains an invalid trash identifier.") from None
    if parts[1] != entry_id:
        raise ValueError("trash_path contains a non-canonical trash identifier.")

    trash_root = sandbox.trash_dir
    entry_dir = trash_root / entry_id
    payload = entry_dir / "payload"
    metadata_path = entry_dir / "metadata.json"
    if trash_root.is_symlink() or getattr(trash_root, "is_junction", lambda: False)():
        raise ValueError("Workspace trash cannot be a symlink or junction.")
    if entry_dir.is_symlink() or getattr(entry_dir, "is_junction", lambda: False)():
        raise ValueError("Trash entries cannot be symlinks or junctions.")
    if not entry_dir.is_dir() or not payload.is_file() or payload.is_symlink():
        raise ValueError("Trash entry was not found or is not a regular file.")
    if not metadata_path.is_file() or metadata_path.is_symlink():
        raise ValueError("Trash metadata was not found or is not a regular file.")
    return entry_dir, payload, metadata_path, sandbox.relative(payload)


def _load_trash_metadata(metadata_path: Path, *, expected_kind: str) -> dict[str, object]:
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Trash metadata is missing or invalid.") from None
    if not isinstance(metadata, dict) or metadata.get("version") != 1:
        raise ValueError("Trash metadata has an unsupported format.")
    if metadata.get("kind") != expected_kind:
        raise ValueError("Trash entry type does not match this operation.")
    return metadata


def _json_result(**values: object) -> str:
    return json.dumps(values, ensure_ascii=False)


def _trash_path_summary(_args, kwargs):
    return {"trash_path": kwargs.get("trash_path")}


def _audit_result_summary(result: object) -> dict[str, object]:
    if not isinstance(result, str):
        return {}
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        key: data[key]
        for key in ("original_path", "trash_path", "path", "removed")
        if key in data
    }


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
Soft-delete one regular file inside the workspace.

The file moves to a unique location under protected .trash storage; it is not
permanently deleted. The JSON result contains original_path and trash_path.
Preserve trash_path so restore_file can restore the file. Protected paths,
symbolic links, and junctions are rejected.
""".strip()

RESTORE_FILE_DESCRIPTION = """
Restore a file moved by delete_file. Pass the exact trash_path returned by
delete_file. The server validates its private metadata and workspace boundary,
then restores to original_path only if no file or directory already exists
there. It never overwrites a conflicting path.
""".strip()

REMOVE_DIRECTORY_DESCRIPTION = """
Remove an empty directory inside the active workspace. This operation never
recurses and refuses non-empty directories; remove or soft-delete contents
explicitly with their own tools first. Workspace boundaries, protected paths,
symbolic links, and junctions are checked.
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
        summarize_result=_audit_result_summary,
    )
    def delete_file(
        path: str = Field(description="Workspace-relative file path."),
    ) -> str:
        return delete_file_impl(sandbox, path)

    @mcp.tool(name="restore_file", description=RESTORE_FILE_DESCRIPTION)
    @audited(
        tool_name="restore_file",
        role=client_id,
        log_path=log_path,
        summarize=_trash_path_summary,
        summarize_result=_audit_result_summary,
    )
    def restore_file(
        trash_path: str = Field(
            description="Exact trash_path returned by delete_file; identifies one private trash entry."
        ),
    ) -> str:
        return restore_file_impl(sandbox, trash_path)

    @mcp.tool(name="remove_directory", description=REMOVE_DIRECTORY_DESCRIPTION)
    @audited(
        tool_name="remove_directory",
        role=client_id,
        log_path=log_path,
        summarize=path_summary,
        summarize_result=_audit_result_summary,
    )
    def remove_directory(
        path: str = Field(description="Workspace-relative path to an empty directory."),
    ) -> str:
        return remove_directory_impl(sandbox, path)
