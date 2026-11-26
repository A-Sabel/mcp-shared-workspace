"""Filesystem tools for the MCP shared workspace."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field

from server.audit_summaries import path_summary, read_summary
from server.audited_tool import audited
from server.config import LIST_LIMIT, MAX_READ_LINES, MAX_READ_RANGES
from server.sandbox import Sandbox, SandboxError
from server.tools.schema_utils import (
    set_array_item_schema,
    set_explicit_required,
    set_property_type,
)

MAX_DEPTH = 10
SCAN_CAP = 5000
SKIP_SCAN_DIRS = {
    ".venv",
    "venv",
    "env",
    ".tox",
    ".nox",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
}
LINECOUNT_MAX_BYTES = 2_000_000
MAX_READ_RESPONSE_BYTES = 64 * 1024
MAX_READ_CONTENT_BYTES = 56 * 1024


class ReadRange(BaseModel):
    """One inclusive, one-based line range for read_file."""

    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(description="Workspace-relative file path.")
    start: int = Field(
        ge=1,
        description="First line number (one-based).",
    )
    end: int = Field(
        ge=1,
        description="Last line number (inclusive).",
    )


def _fmt_size(size: int) -> str:
    """Format a byte count compactly."""
    if size < 1024:
        return f"{size} B"

    if size < 1024**2:
        return f"{size / 1024:.1f} KB"

    return f"{size / 1024**2:.1f} MB"


def _line_info(path: Path, size: int) -> str:
    """Return line count, binary marker, or empty when unavailable."""
    if size == 0:
        return "0 lines"

    if size > LINECOUNT_MAX_BYTES:
        return ""

    try:
        with path.open("rb") as fh:
            head = fh.read(8192)

            if b"\x00" in head:
                return "binary"

            count = head.count(b"\n")
            last = head[-1:]

            while chunk := fh.read(65536):
                count += chunk.count(b"\n")
                last = chunk[-1:]

    except OSError:
        return ""

    if last != b"\n":
        count += 1

    return f"{count} line" + ("" if count == 1 else "s")


@lru_cache(maxsize=256)
def _compile_glob(pattern: str) -> re.Pattern[str]:
    """Translate a glob into a path-aware regex.

    ``*`` and ``?`` never cross a ``/``. A ``**`` that forms a whole path
    segment matches across directories: ``**/`` means zero or more leading
    directories, and a trailing ``**`` means everything below. Anywhere else
    ``**`` behaves like ``*``.
    """
    out: list[str] = []
    i, n = 0, len(pattern)

    while i < n:
        char = pattern[i]

        if char == "*":
            end = i
            while end < n and pattern[end] == "*":
                end += 1
            whole_segment_start = i == 0 or pattern[i - 1] == "/"

            if end - i >= 2 and whole_segment_start and end < n and pattern[end] == "/":
                out.append("(?:.*/)?")
                i = end + 1
            elif end - i >= 2 and whole_segment_start and end == n:
                out.append(".*")
                i = end
            else:
                out.append("[^/]*")
                i = end

        elif char == "?":
            out.append("[^/]")
            i += 1

        elif char == "[":
            j = i + 1
            if j < n and pattern[j] in "!^":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1

            if j >= n:
                out.append(re.escape(char))
                i += 1
            else:
                body = pattern[i + 1 : j].replace("\\", "\\\\")
                if body.startswith(("!", "^")):
                    body = "^" + body[1:]
                out.append(f"[{body}]")
                i = j + 1

        else:
            out.append(re.escape(char))
            i += 1

    # Match fnmatch's historical behaviour: case-insensitive where the OS is.
    flags = re.IGNORECASE if os.path.normcase("A") == "a" else 0
    return re.compile("".join(out), flags)


def _glob_match(relative_path: str, pattern: str) -> bool:
    """Match a filename or workspace-relative path against a glob.

    A pattern without ``/`` is matched against the file name alone, so
    ``*.py`` finds Python files at any depth. A pattern containing ``/`` is
    matched against the whole relative path, where ``*`` stays inside one
    directory (``src/*.py`` does not match ``src/a/b.py``) and ``**`` crosses
    directories (``src/**/*.py`` does).
    """
    target = relative_path if "/" in pattern else relative_path.rsplit("/", 1)[-1]
    return _compile_glob(pattern).fullmatch(target) is not None


def _read_result_summary(result: object) -> dict[str, object]:
    """Extract only non-content read coverage fields for audit telemetry."""
    if not isinstance(result, str):
        return {}
    try:
        payload = json.loads(result)
    except (TypeError, json.JSONDecodeError):
        return {}
    ranges = payload.get("ranges") if isinstance(payload, dict) else None
    if not isinstance(ranges, list):
        return {}
    coverage = []
    for item in ranges:
        if not isinstance(item, dict):
            continue
        coverage.append(
            {
                "path": item.get("path"),
                "start_line": item.get("start_line"),
                "end_line": item.get("end_line"),
                "total_lines": item.get("total_lines"),
                "has_more": item.get("has_more"),
                "next_start_line": item.get("next_start_line"),
            }
        )
    return {"read_ranges": coverage}


def _ignored_paths(sandbox: Sandbox, paths: Sequence[Path]) -> set[str]:
    """Return Git-ignored workspace-relative paths; fail open if Git is unavailable."""
    if (
        not paths
        or shutil.which("git") is None
        or not (sandbox.root / ".git").exists()
    ):
        return set()
    relative = [sandbox.relative(path) for path in paths]
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-z", "--stdin"],
            cwd=sandbox.root,
            input="\0".join(relative) + "\0",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
        )
    except OSError:
        return set()
    if result.returncode not in (0, 1):
        return set()
    return {item for item in result.stdout.split("\0") if item}


def _missing_path_message(sandbox: Sandbox, path: str) -> str:
    """Build a 'does not exist' message with close-name suggestions.

    Finds the first path component that does not exist, then offers the
    closest sibling names from the deepest directory that does. Falls back
    to the plain message if anything goes wrong.
    """
    plain = (
        f"Path {path!r} does not exist. "
        "Call list_files with path='.' to see what exists."
    )
    parts = [
        part
        for part in path.replace("\\", "/").split("/")
        if part not in ("", ".")
    ]
    if not parts or ".." in parts:
        return plain

    try:
        current = "."
        for part in parts:
            parent = sandbox.resolve(current)
            if (parent / part).exists():
                current = part if current == "." else f"{current}/{part}"
                continue

            names = sorted(
                entry.name
                for entry in os.scandir(parent)
                if not sandbox.is_protected(Path(entry.path))
            )
            by_lower = {name.lower(): name for name in names}
            close = difflib.get_close_matches(
                part.lower(), list(by_lower), n=3, cutoff=0.6
            )
            matches = [by_lower[name] for name in close]
            prefix = "" if current == "." else f"{current}/"
            location = "the workspace root" if current == "." else repr(current)

            if matches:
                options = ", ".join(repr(prefix + match) for match in matches)
                return (
                    f"Path {path!r} does not exist. "
                    f"Did you mean: {options}? "
                    "Call list_files with path='.' to see what exists."
                )
            return (
                f"Path {path!r} does not exist "
                f"({part!r} was not found in {location}). "
                f"Call list_files with path={current!r} to see what is there."
            )
    except (OSError, SandboxError):
        return plain

    return plain


def _walk(
    sandbox: Sandbox,
    directory: Path,
    depth: int,
    max_depth: int,
    output: list[tuple[Path, bool]],
) -> None:
    """Walk shallow-first so root files survive the bounded scan.

    Git-ignored entries are dropped one tree level at a time (a single
    ``git check-ignore`` call per level), so ignored or generated folders such
    as ``dist/`` or ``build/`` neither use up SCAN_CAP nor get descended into.
    Outside a Git repo, or without Git, nothing extra is filtered.
    """
    level = [(directory, depth)]

    while level and len(output) < SCAN_CAP:
        level_entries: list[tuple[Path, bool, int]] = []

        for current, current_depth in level:
            try:
                with os.scandir(current) as entries:
                    entries = sorted(
                        entries,
                        key=lambda entry: (
                            entry.is_dir(follow_symlinks=False),
                            entry.name.lower(),
                        ),
                    )
            except OSError:
                continue

            for entry in entries:
                # Do not follow symlinks during directory enumeration.
                if entry.is_symlink():
                    continue

                is_dir = entry.is_dir(follow_symlinks=False)
                if not is_dir and not entry.is_file(follow_symlinks=False):
                    continue

                path = Path(entry.path)
                if sandbox.is_protected(path):
                    continue

                if is_dir and entry.name.lower() in SKIP_SCAN_DIRS:
                    continue

                level_entries.append((path, is_dir, current_depth))

        ignored = _ignored_paths(
            sandbox, [path for path, _, _ in level_entries]
        )
        next_level: list[tuple[Path, int]] = []

        for path, is_dir, current_depth in level_entries:
            if len(output) >= SCAN_CAP:
                break

            if sandbox.relative(path) in ignored:
                continue

            output.append((path, is_dir))
            if is_dir and current_depth < max_depth:
                next_level.append((path, current_depth + 1))

        level = next_level


def list_files_impl(
    sandbox: Sandbox,
    path: str = ".",
    glob: str | None = None,
    max_depth: int = 1,
    limit: int = LIST_LIMIT,
    include_details: bool = False,
) -> str:
    """Implementation of the list_files operation."""
    base = sandbox.resolve(path)

    if not base.exists():
        raise SandboxError(_missing_path_message(sandbox, path))

    if base.is_file():
        if sandbox.relative(base) in _ignored_paths(sandbox, [base]):
            return f"{sandbox.relative(base)} (ignored by Git .gitignore)"
        if not include_details:
            return sandbox.relative(base)
        size = base.stat().st_size

        parts = (
            sandbox.relative(base),
            _fmt_size(size),
            _line_info(base, size),
        )

        return "  ".join(part for part in parts if part)

    found: list[tuple[Path, bool]] = []

    _walk(
        sandbox,
        base,
        depth=1,
        max_depth=max_depth,
        output=found,
    )

    # _walk already drops Git-ignored entries, so `found` is the true scan result
    # and hitting SCAN_CAP here means real entries were left unscanned.
    capped = len(found) >= SCAN_CAP

    if glob:
        found = [
            (item_path, is_dir)
            for item_path, is_dir in found
            if not is_dir
            and _glob_match(
                item_path.relative_to(base).as_posix(),
                glob,
            )
        ]

    found.sort(key=lambda item: (sandbox.relative(item[0]).casefold(), sandbox.relative(item[0])))
    total = len(found)

    scope = f"depth {max_depth}"

    if glob:
        scope += f", glob {glob!r}"

    header = (
        f"{sandbox.relative(base)} ({scope}): "
        f"{total}{'+' if capped else ''} "
        f"item{'s' if total != 1 or capped else ''}"
    )

    lines = [header]

    if total == 0:
        if glob:
            lines.append("(no matches; try a broader glob or a larger max_depth)")
        else:
            lines.append("(empty)")

    for item_path, is_dir in found[:limit]:
        relative = item_path.relative_to(base).as_posix()

        if is_dir:
            lines.append(relative + "/")
            continue

        if not include_details:
            lines.append(relative)
            continue
        size = item_path.stat().st_size

        parts = (
            relative,
            _fmt_size(size),
            _line_info(item_path, size),
        )

        lines.append("  ".join(part for part in parts if part))

    if total > limit or capped:
        lines.append(
            f"[showing {min(limit, total)} of "
            f"{total}{'+' if capped else ''}; "
            "narrow with path= or glob=, or lower max_depth]"
        )

    return "\n".join(lines)


READ_FILE_DESCRIPTION = (
    "Read a workspace-relative file in bounded line chunks and return its SHA-256 hash for optimistic concurrency checks. For one chunk, "
    "provide path, start_line, and optionally end_line. Line numbers are "
    "one-based and inclusive; the server returns at most 200 lines per range. "
    "Oversized ranges are capped automatically; check requested_end_line, "
    "has_more, and next_start_line to continue. Paths are relative to the active "
    "workspace; if a path is missing, use list_files rather than guessing. "
    "When you already know more context is needed, use ranges to "
    "request up to five chunks/files in one call. For sequential chunks of the "
    "same file, set each range's start to the prior chunk's next_start_line. "
    "By default the server stops after the requested range and one-line "
    "lookahead; total_lines is omitted unless EOF was reached naturally. Set "
    "count_total_lines=true to scan through EOF for an exact total. Each result "
    "includes has_more and next_start_line for continuation. "
    "Use your judgment to decide whether the returned content is enough for "
    "the task; has_more only indicates that unread content remains. If more "
    "context is needed, call read_file again with start_line=next_start_line, "
    "or batch up to five known-needed chunks with ranges. "
    "For complete-file tasks, continue until has_more is false. If a "
    "task covers multiple files, inspect each requested file and all required "
    "chunks, then report any file or range that could not be completed. "
    "Responses are capped at 64 KiB; a byte-limited chunk can be continued."
)


LIST_FILES_DESCRIPTION = (
    "List workspace files and folders as relative paths. Set include_details=true "
    "to add file sizes and line counts. Use glob to find files by name. "
    "Use search_files to find text inside files. Protected paths and Git-ignored files are hidden when Git is available. "
    "Output is bounded; narrow with path, glob, or max_depth if truncated."
)


def register(
    mcp: MCPServer,
    sandbox: Sandbox,
    client_id: str = "workspace-client",
    log_path: Path | None = None,
) -> None:
    """Register filesystem tools when the supplied role is authorized."""

    if log_path is None:
        log_path = sandbox.root / ".tool_calls.jsonl"

    if True:

        @audited(
            tool_name="list_files",
            role=client_id,
            log_path=log_path,
            summarize=path_summary,
        )
        def list_files(
            path: Annotated[
                str,
                Field(
                    description=(
                        "Workspace-relative directory or file path. "
                        "Use '.' for the workspace root."
                    ),
                ),
            ] = ".",
            glob: Annotated[
                str | None,
                Field(
                    max_length=200,
                    description=(
                        "Optional filename or relative-path glob, "
                        "for example '*.py'."
                    ),
                ),
            ] = None,
            max_depth: Annotated[
                int,
                Field(
                    ge=1,
                    le=MAX_DEPTH,
                    description="Maximum directory depth to descend.",
                ),
            ] = 1,
            limit: Annotated[
                int,
                Field(
                    ge=1,
                    le=LIST_LIMIT,
                    description="Maximum number of entries to return.",
                ),
            ] = LIST_LIMIT,
            include_details: Annotated[
                bool,
                Field(
                    description="Include file sizes and line counts; defaults to false for compact output.",
                ),
            ] = False,
        ) -> str:
            """List files and folders in the sandboxed workspace."""
            try:
                return list_files_impl(
                    sandbox,
                    path,
                    glob,
                    max_depth,
                    limit,
                    include_details,
                )
            except (SandboxError, OSError) as exc:
                raise ValueError(str(exc)) from None

        mcp.add_tool(
            list_files,
            name="list_files",
            description=LIST_FILES_DESCRIPTION,
            structured_output=False,
        )
        set_explicit_required(mcp, "list_files")
        set_property_type(mcp, "list_files", "glob", "string")

    if True:

        @audited(
            tool_name="read_file",
            role=client_id,
            log_path=log_path,
            summarize=read_summary,
            summarize_result=_read_result_summary,
        )
        def read_file(
            path: Annotated[
                str | None,
                Field(
                    description=(
                        "Path relative to the active workspace. Discover valid "
                        "paths with list_files; do not use local absolute paths."
                    ),
                ),
            ] = None,
            start_line: Annotated[
                int,
                Field(
                    ge=1,
                    description="One-based inclusive first line.",
                ),
            ] = 1,
            end_line: Annotated[
                int | None,
                Field(
                    ge=1,
                    description=(
                        "One-based inclusive last line. Requests over 200 lines "
                        "are capped; continue with next_start_line."
                    ),
                ),
            ] = None,
            ranges: Annotated[
                list[ReadRange] | None,
                Field(
                    min_length=1,
                    max_length=MAX_READ_RANGES,
                    description=(
                        "Optional list of up to five {path, start, end} chunks; "
                        "each oversized chunk is capped at 200 lines. Use multiple "
                        "ranges to batch chunks you already know "
                        "are needed; for sequential chunks, continue from each "
                        "prior result's next_start_line."
                    ),
                ),
            ] = None,
            count_total_lines: Annotated[
                bool,
                Field(
                    description=(
                        "Whether to scan through EOF to return an exact "
                        "total_lines value. Defaults to false for targeted reads."
                    ),
                ),
            ] = False,
        ) -> str:
            """Read a bounded file chunk and report how to continue reading."""
            try:
                if ranges is not None:
                    if path is not None:
                        raise ValueError("Provide either ranges or path, not both.")
                    requested = ranges
                elif path is not None:
                    requested_end = end_line or min(start_line + MAX_READ_LINES - 1, 2**31 - 1)
                    requested = [{"path": path, "start": start_line, "end": requested_end}]
                else:
                    raise ValueError("Provide path or ranges.")
                return read_file_result_impl(
                    sandbox,
                    requested,
                    count_total_lines=count_total_lines,
                )
            except (SandboxError, ValueError) as exc:
                raise ValueError(str(exc)) from None

        mcp.add_tool(
            read_file,
            name="read_file",
            description=READ_FILE_DESCRIPTION,
            structured_output=False,
        )
        set_explicit_required(
            mcp,
            "read_file",
            one_of=[
                {
                    "required": ["path"],
                    "properties": {"path": {"type": "string"}},
                },
                {
                    "required": ["ranges"],
                    "properties": {"ranges": {"type": "array"}},
                },
            ],
        )
        set_property_type(mcp, "read_file", "path", "string")
        set_property_type(mcp, "read_file", "end_line", "integer")
        set_property_type(mcp, "read_file", "count_total_lines", "boolean")
        set_array_item_schema(
            mcp,
            "read_file",
            "ranges",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "start": {"type": "integer", "minimum": 1},
                    "end": {"type": "integer", "minimum": 1},
                },
                "required": ["path", "start", "end"],
            },
        )


def read_file_impl(
    sandbox: Sandbox,
    ranges: Sequence[ReadRange | dict[str, object]],
) -> str:
    """Read bounded, possibly non-contiguous line ranges via the sandbox."""
    if not isinstance(ranges, list):
        raise ValueError("ranges must be a list.")

    if not ranges:
        raise ValueError("At least one range is required.")

    if len(ranges) > MAX_READ_RANGES:
        raise ValueError(f"At most {MAX_READ_RANGES} ranges are allowed.")

    sections: list[str] = []

    for index, item in enumerate(ranges, start=1):
        try:
            spec = (
                item if isinstance(item, ReadRange) else ReadRange.model_validate(item)
            )
        except Exception as exc:
            raise ValueError(f"Invalid range {index}: {exc}") from None

        if spec.end < spec.start:
            raise ValueError(
                f"Range {index}: end must be greater than or equal to start."
            )

        requested_end = spec.end
        effective_end = min(spec.end, spec.start + MAX_READ_LINES - 1)

        path = sandbox.resolve(spec.path)

        if not path.exists():
            raise ValueError(
                f"Range {index}: file {spec.path!r} does not exist in the active "
                "workspace. Use list_files to discover the correct relative path."
            )

        if not path.is_file():
            raise ValueError(
                f"Range {index}: path {spec.path!r} is not a file. "
                "Use list_files to inspect workspace paths."
            )

        try:
            with path.open("r", encoding="utf-8") as stream:
                selected: list[str] = []

                for line_number, line in enumerate(stream, start=1):
                    if line_number > effective_end:
                        break

                    if line_number >= spec.start:
                        selected.append(
                            f"{line_number}: " f"{line.rstrip(chr(10)).rstrip(chr(13))}"
                        )

        except UnicodeDecodeError:
            raise ValueError(
                f"Range {index}: file {spec.path!r} " "is not valid UTF-8 text."
            ) from None

        except OSError as exc:
            detail = exc.strerror or "I/O error"

            raise ValueError(
                f"Range {index}: cannot read file " f"{spec.path!r}: {detail}."
            ) from None

        content = "\n".join(selected) if selected else "(no lines in requested range)"

        section = f"{spec.path}:{spec.start}-{effective_end}\n{content}"
        if effective_end < requested_end:
            section += (
                f"\n[requested through line {requested_end}; capped at "
                f"{MAX_READ_LINES} lines, continue from line {effective_end + 1}]"
            )
        sections.append(section)

    return "\n\n".join(sections)


def _file_sha256(path: Path) -> str:
    """Hash a file incrementally without loading its full contents into memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_file_result_impl(
    sandbox: Sandbox,
    ranges: Sequence[ReadRange | dict[str, object]],
    *,
    count_total_lines: bool = False,
) -> str:
    """Read bounded ranges, optionally scanning to EOF for exact line totals."""
    if not isinstance(ranges, list) or not ranges:
        raise ValueError("At least one range is required.")
    if len(ranges) > MAX_READ_RANGES:
        raise ValueError(f"At most {MAX_READ_RANGES} ranges are allowed.")

    results: list[dict[str, object]] = []
    used_bytes = 0
    for index, item in enumerate(ranges, start=1):
        try:
            spec = item if isinstance(item, ReadRange) else ReadRange.model_validate(item)
        except Exception as exc:
            raise ValueError(f"Invalid range {index}: {exc}") from None
        if spec.end < spec.start:
            raise ValueError(f"Range {index}: end must be greater than or equal to start.")
        requested_end = spec.end
        effective_end = min(spec.end, spec.start + MAX_READ_LINES - 1)

        file_path = sandbox.resolve(spec.path)
        if not file_path.exists():
            raise ValueError(
                f"Range {index}: file {spec.path!r} does not exist in the active "
                "workspace. Use list_files to discover the correct relative path."
            )
        if not file_path.is_file():
            raise ValueError(
                f"Range {index}: path {spec.path!r} is not a file. "
                "Use list_files to inspect workspace paths."
            )

        lines: list[str] = []
        returned_end = spec.start - 1
        total_lines: int | None = None
        line_count = 0
        has_more = False
        before_stat = file_path.stat()
        try:
            with file_path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    line_count = line_number
                    if line_number < spec.start:
                        continue
                    if line_number > effective_end:
                        # One-line lookahead proves there is unread content.
                        has_more = True
                        if not count_total_lines:
                            break
                        continue
                    rendered = f"{line_number}: {line.rstrip(chr(10)).rstrip(chr(13))}"
                    escaped_bytes = len(json.dumps(rendered, ensure_ascii=False).encode("utf-8"))
                    extra = escaped_bytes + (2 if lines else 0)
                    if used_bytes + extra > MAX_READ_CONTENT_BYTES:
                        if not lines and used_bytes == 0:
                            raise ValueError(
                                f"Range {index}: line {line_number} exceeds the read response size limit."
                            )
                        has_more = True
                        if not count_total_lines:
                            break
                    else:
                        lines.append(rendered)
                        used_bytes += extra
                        returned_end = line_number
                else:
                    total_lines = line_count
            sha256 = _file_sha256(file_path)
            after_stat = file_path.stat()
            if (
                before_stat.st_size != after_stat.st_size
                or before_stat.st_mtime_ns != after_stat.st_mtime_ns
                or before_stat.st_ino != after_stat.st_ino
            ):
                raise ValueError(
                    f"Range {index}: file {spec.path!r} changed while being read; retry the read."
                )
        except UnicodeDecodeError:
            raise ValueError(f"Range {index}: file {spec.path!r} is not valid UTF-8 text.") from None
        except OSError as exc:
            detail = exc.strerror or "I/O error"
            raise ValueError(f"Range {index}: cannot read file {spec.path!r}: {detail}.") from None

        if count_total_lines:
            has_more = returned_end < (total_lines or 0) and (total_lines or 0) >= spec.start
        result: dict[str, object] = {
            "path": spec.path,
            "sha256": sha256,
            "start_line": spec.start,
            "requested_end_line": requested_end,
            "has_more": has_more,
            "content": "\n".join(lines) if lines else "(no lines in requested range)",
        }
        if returned_end >= spec.start:
            result["end_line"] = returned_end
        if total_lines is not None:
            result["total_lines"] = total_lines
        if has_more:
            result["next_start_line"] = returned_end + 1
        results.append(result)

    result = json.dumps({"ranges": results}, ensure_ascii=False)
    if len(result.encode("utf-8")) > MAX_READ_RESPONSE_BYTES:
        raise ValueError("Read response metadata exceeds the response size limit; request fewer ranges.")
    return result
