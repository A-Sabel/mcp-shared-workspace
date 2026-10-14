"""Filesystem tools for the MCP shared workspace."""

from __future__ import annotations

import fnmatch
import json
import os
from collections.abc import Sequence
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


def _glob_match(relative_path: str, pattern: str) -> bool:
    """Match a filename or workspace-relative path against a glob."""
    patterns = [pattern]

    if pattern.startswith("**/"):
        patterns.append(pattern[3:])

    filename = relative_path.rsplit("/", 1)[-1]

    return any(
        fnmatch.fnmatch(
            relative_path if "/" in pat else filename,
            pat,
        )
        for pat in patterns
    )


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


def _walk(
    sandbox: Sandbox,
    directory: Path,
    depth: int,
    max_depth: int,
    output: list[tuple[Path, bool]],
) -> None:
    """Walk directories while skipping protected and unsafe entries."""
    try:
        with os.scandir(directory) as entries:
            entries = sorted(
                entries,
                key=lambda entry: (
                    not entry.is_dir(follow_symlinks=False),
                    entry.name.lower(),
                ),
            )
    except OSError:
        return

    for entry in entries:
        if len(output) >= SCAN_CAP:
            return

        # Do not follow symlinks during directory enumeration.
        if entry.is_symlink():
            continue

        is_dir = entry.is_dir(follow_symlinks=False)

        if not is_dir and not entry.is_file(follow_symlinks=False):
            continue

        path = Path(entry.path)

        if sandbox.is_protected(path):
            continue

        output.append((path, is_dir))

        if is_dir and depth < max_depth:
            _walk(
                sandbox,
                path,
                depth + 1,
                max_depth,
                output,
            )


def list_files_impl(
    sandbox: Sandbox,
    path: str = ".",
    glob: str | None = None,
    max_depth: int = 1,
    limit: int = LIST_LIMIT,
) -> str:
    """Implementation of the list_files operation."""
    base = sandbox.resolve(path)

    if not base.exists():
        raise SandboxError(
            f"Path {path!r} does not exist. "
            "Call list_files with path='.' to see what exists."
        )

    if base.is_file():
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
    "Read a workspace-relative file in bounded line chunks. For one chunk, "
    "provide path, start_line, and optionally end_line; the default is at most "
    "200 lines. Or provide ranges for up to five chunks/files. The JSON result "
    "includes total_lines, has_more, and next_start_line for every chunk. "
    "When asked to read a complete file, continue from next_start_line until "
    "has_more is false; do not treat the first chunk as the whole file. If a "
    "task covers multiple files, inspect each requested file and all required "
    "chunks, then report any file or range that could not be completed. "
    "Responses are capped at 64 KiB; a byte-limited chunk can be continued."
)


LIST_FILES_DESCRIPTION = (
    "List workspace files and folders as relative paths with size and line "
    "count. Use first to see what exists, or use glob to find files by name. "
    "Use search_files to find text inside files. Protected paths are hidden. "
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
                str,
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
        ) -> str:
            """List files and folders in the sandboxed workspace."""
            try:
                return list_files_impl(
                    sandbox,
                    path,
                    glob,
                    max_depth,
                    limit,
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
                str,
                Field(
                    description="Workspace-relative file path for a single chunk.",
                ),
            ] = None,
            start_line: Annotated[
                int,
                Field(ge=1, description="One-based first line; defaults to 1."),
            ] = 1,
            end_line: Annotated[
                int,
                Field(ge=1, description="One-based inclusive last line; defaults to at most 200 lines."),
            ] = None,
            ranges: Annotated[
                list[ReadRange],
                Field(
                    min_length=1,
                    max_length=MAX_READ_RANGES,
                    description="Optional list of up to five {path, start, end} chunks.",
                ),
            ] = None,
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
                return read_file_result_impl(sandbox, requested)
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

        if spec.end - spec.start + 1 > MAX_READ_LINES:
            raise ValueError(
                f"Range {index}: at most {MAX_READ_LINES} lines are allowed."
            )

        path = sandbox.resolve(spec.path)

        if not path.exists():
            raise ValueError(f"Range {index}: file {spec.path!r} does not exist.")

        if not path.is_file():
            raise ValueError(f"Range {index}: path {spec.path!r} is not a file.")

        try:
            with path.open("r", encoding="utf-8") as stream:
                selected: list[str] = []

                for line_number, line in enumerate(stream, start=1):
                    if line_number > spec.end:
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

        sections.append(f"{spec.path}:{spec.start}-{spec.end}\n{content}")

    return "\n\n".join(sections)


def read_file_result_impl(
    sandbox: Sandbox,
    ranges: Sequence[ReadRange | dict[str, object]],
) -> str:
    """Read line ranges with completion metadata and a serialized-size cap."""
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
        if spec.end - spec.start + 1 > MAX_READ_LINES:
            raise ValueError(f"Range {index}: at most {MAX_READ_LINES} lines are allowed.")

        file_path = sandbox.resolve(spec.path)
        if not file_path.exists():
            raise ValueError(f"Range {index}: file {spec.path!r} does not exist.")
        if not file_path.is_file():
            raise ValueError(f"Range {index}: path {spec.path!r} is not a file.")

        lines: list[str] = []
        returned_end = spec.start - 1
        total_lines = 0
        byte_limited = False
        try:
            with file_path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    total_lines = line_number
                    if not spec.start <= line_number <= spec.end or byte_limited:
                        continue
                    rendered = f"{line_number}: {line.rstrip(chr(10)).rstrip(chr(13))}"
                    escaped_bytes = len(json.dumps(rendered, ensure_ascii=False).encode("utf-8"))
                    extra = escaped_bytes + (2 if lines else 0)
                    if used_bytes + extra > MAX_READ_CONTENT_BYTES:
                        if not lines and used_bytes == 0:
                            raise ValueError(
                                f"Range {index}: line {line_number} exceeds the read response size limit."
                            )
                        byte_limited = True
                        continue
                    lines.append(rendered)
                    used_bytes += extra
                    returned_end = line_number
        except UnicodeDecodeError:
            raise ValueError(f"Range {index}: file {spec.path!r} is not valid UTF-8 text.") from None
        except OSError as exc:
            detail = exc.strerror or "I/O error"
            raise ValueError(f"Range {index}: cannot read file {spec.path!r}: {detail}.") from None

        has_more = returned_end < total_lines and total_lines >= spec.start
        results.append(
            {
                "path": spec.path,
                "start_line": spec.start,
                "end_line": returned_end if returned_end >= spec.start else None,
                "requested_end_line": spec.end,
                "total_lines": total_lines,
                "has_more": has_more,
                "next_start_line": returned_end + 1 if has_more else None,
                "content": "\n".join(lines) if lines else "(no lines in requested range)",
            }
        )

    result = json.dumps({"ranges": results}, ensure_ascii=False)
    if len(result.encode("utf-8")) > MAX_READ_RESPONSE_BYTES:
        raise ValueError("Read response metadata exceeds the response size limit; request fewer ranges.")
    return result
