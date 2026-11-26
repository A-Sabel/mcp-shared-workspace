"""Search tools for the MCP shared workspace."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from server.audit_summaries import search_summary
from server.audited_tool import audited
from server.config import SEARCH_LIMIT, SNIPPET_CHARS
from server.sandbox import Sandbox, SandboxError
from server.tools.schema_utils import set_property_type
from server.tools.file_tools import (
    SCAN_CAP,
    _glob_match,
    _ignored_paths,
    _missing_path_message,
    _walk,
)

MAX_SEARCH_FILE_BYTES = 5_000_000
MAX_MATCHES_PER_FILE = 5
MAX_CAPPED_FILE_NOTES = 5
SCAN_LIMIT_NOTE = (
    f"[scan limit reached: only the first {SCAN_CAP} entries were scanned, "
    "so results may be incomplete; narrow with path= or glob=]"
)


def search_files_impl(
    sandbox: Sandbox,
    query: str,
    path: str = ".",
    glob: str | None = None,
    regex: bool = False,
    limit: int = SEARCH_LIMIT,
    per_file_limit: int = MAX_MATCHES_PER_FILE,
) -> str:
    """Search workspace text files and return compact matching lines.

    At most ``per_file_limit`` matches are shown per file so one noisy file
    (a lockfile, a minified bundle) cannot use up the whole result budget.
    Searching a single file by path is not subject to that cap.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be empty.")

    if limit < 1 or limit > SEARCH_LIMIT:
        raise ValueError(f"limit must be between 1 and {SEARCH_LIMIT}.")

    if per_file_limit < 1:
        raise ValueError("per_file_limit must be at least 1.")

    base = sandbox.resolve(path)
    scan_capped = False

    if not base.exists():
        raise SandboxError(_missing_path_message(sandbox, path))

    if base.is_file():
        candidates = [base]
        # The caller named this file explicitly, so show all of its matches.
        per_file_limit = limit

    elif base.is_dir():
        found: list[tuple[Path, bool]] = []

        _walk(
            sandbox,
            base,
            depth=1,
            max_depth=10,
            output=found,
        )

        # _walk stops exactly at SCAN_CAP, so hitting it means entries were dropped.
        scan_capped = len(found) >= SCAN_CAP
        candidates = [item_path for item_path, is_dir in found if not is_dir]

    else:
        raise SandboxError(f"Path {path!r} is not a file or directory.")

    # Directory walks already exclude Git-ignored entries; only an explicitly
    # named file still needs the check.
    if base.is_file():
        ignored = _ignored_paths(sandbox, candidates)
        candidates = [
            candidate for candidate in candidates
            if sandbox.relative(candidate) not in ignored
        ]

    if glob:
        candidates = [
            candidate
            for candidate in candidates
            if (
                _glob_match(candidate.name, glob)
                or _glob_match(sandbox.relative(candidate), glob)
            )
        ]
        if not candidates:
            message = f"No files matched glob {glob!r} under {path!r}."
            if scan_capped:
                message += f"\n{SCAN_LIMIT_NOTE}"
            return message

    candidates.sort(key=lambda candidate: (sandbox.relative(candidate).casefold(), sandbox.relative(candidate)))

    glob_candidate_count = len(candidates) if glob else None

    pattern = None

    if regex:
        try:
            pattern = re.compile(query)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression: {exc}") from None

    results: list[str] = []
    capped_files: list[tuple[str, int]] = []

    for candidate in candidates:
        if len(results) >= limit:
            break

        if sandbox.is_protected(candidate):
            continue

        file_hits = 0
        hidden_hits = 0

        try:
            if candidate.stat().st_size > MAX_SEARCH_FILE_BYTES:
                continue

            with candidate.open(
                "r",
                encoding="utf-8",
                errors="strict",
            ) as stream:
                for line_number, line in enumerate(
                    stream,
                    start=1,
                ):
                    text = line.rstrip("\r\n")

                    matched = (
                        bool(pattern.search(text))
                        if pattern is not None
                        else query in text
                    )

                    if not matched:
                        continue

                    file_hits += 1

                    if file_hits > per_file_limit:
                        # Keep counting so the note can say how many were hidden.
                        hidden_hits += 1
                        continue

                    snippet = text.strip()

                    if len(snippet) > SNIPPET_CHARS:
                        snippet = snippet[:SNIPPET_CHARS].rstrip() + "..."

                    results.append(
                        f"{sandbox.relative(candidate)}:" f"{line_number}: {snippet}"
                    )

                    if len(results) >= limit:
                        break

        except UnicodeDecodeError:
            # Skip binary/non-UTF-8 files.
            continue

        except OSError:
            # Skip files that disappear or become unreadable.
            continue

        finally:
            if hidden_hits:
                capped_files.append((sandbox.relative(candidate), hidden_hits))

    if not results:
        if glob_candidate_count is not None:
            message = (
                f"No content matches for query in the {glob_candidate_count} "
                f"file(s) matched by glob {glob!r}."
            )
        else:
            message = "No matches."
        if scan_capped:
            message += f"\n{SCAN_LIMIT_NOTE}"
        return message

    output = [f"Found {len(results)} " f"match{'es' if len(results) != 1 else ''}:"]

    output.extend(results)

    for capped_path, hidden in capped_files[:MAX_CAPPED_FILE_NOTES]:
        output.append(
            f"[{capped_path}: +{hidden} more match{'es' if hidden != 1 else ''} "
            f"not shown (per-file limit {per_file_limit}); "
            "search that file with path= to see all]"
        )

    if len(capped_files) > MAX_CAPPED_FILE_NOTES:
        extra_files = len(capped_files) - MAX_CAPPED_FILE_NOTES
        output.append(
            f"[{extra_files} more file{'s' if extra_files != 1 else ''} "
            "also hit the per-file limit]"
        )

    if len(results) >= limit:
        output.append(
            f"[result limit reached: {limit}; "
            "narrow with path= or glob=, "
            "or increase specificity]"
        )

    if scan_capped:
        output.append(SCAN_LIMIT_NOTE)

    return "\n".join(output)


SEARCH_FILES_DESCRIPTION = (
    "Search text inside workspace files and return compact "
    "path:line:snippet matches. Use this to locate relevant "
    "code or text before calling read_file. Literal matching "
    "is used by default; set regex=true only when a regular "
    "expression is needed. Protected paths are skipped and "
    "results are bounded."
)


def register(
    mcp: MCPServer,
    sandbox: Sandbox,
    client_id: str = "workspace-client",
    log_path: Path | None = None,
) -> None:
    """Register search_files when the supplied role is authorized."""

    if log_path is None:
        log_path = sandbox.root / ".tool_calls.jsonl"

    @audited(
        tool_name="search_files",
        role=client_id,
        log_path=log_path,
        summarize=search_summary,
    )
    def search_files(
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=500,
                description=("Text or regular expression to search for."),
            ),
        ],
        path: Annotated[
            str,
            Field(
                description=(
                    "Workspace-relative file or directory to search. "
                    "Use '.' for the workspace root."
                ),
            ),
        ] = ".",
        glob: Annotated[
            str | None,
            Field(
                max_length=200,
                description=(
                    "Optional filename or workspace-relative path glob, "
                    "for example 'hello_world.py', '*.py', or 'src/*.py'. "
                    "Matching files must also contain query."
                ),
            ),
        ] = None,
        regex: Annotated[
            bool,
            Field(
                description=(
                    "Interpret query as a regular expression. "
                    "False uses literal matching."
                ),
            ),
        ] = False,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=SEARCH_LIMIT,
                description=("Maximum number of matching lines to return."),
            ),
        ] = SEARCH_LIMIT,
    ) -> str:
        """Search workspace files and return compact matching lines."""
        try:
            return search_files_impl(
                sandbox,
                query,
                path,
                glob,
                regex,
                limit,
            )
        except (SandboxError, ValueError) as exc:
            raise ValueError(str(exc)) from None

    mcp.add_tool(
        search_files,
        name="search_files",
        description=SEARCH_FILES_DESCRIPTION,
        structured_output=False,
    )
    set_property_type(mcp, "search_files", "glob", "string")
