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
from server.tools.file_tools import _glob_match, _walk

MAX_SEARCH_FILE_BYTES = 5_000_000


def search_files_impl(
    sandbox: Sandbox,
    query: str,
    path: str = ".",
    glob: str | None = None,
    regex: bool = False,
    limit: int = SEARCH_LIMIT,
) -> str:
    """Search workspace text files and return compact matching lines."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be empty.")

    if limit < 1 or limit > SEARCH_LIMIT:
        raise ValueError(f"limit must be between 1 and {SEARCH_LIMIT}.")

    base = sandbox.resolve(path)

    if not base.exists():
        raise SandboxError(
            f"Path {path!r} does not exist. "
            "Call list_files with path='.' to see what exists."
        )

    if base.is_file():
        candidates = [base]

    elif base.is_dir():
        found: list[tuple[Path, bool]] = []

        _walk(
            sandbox,
            base,
            depth=1,
            max_depth=10,
            output=found,
        )

        candidates = [item_path for item_path, is_dir in found if not is_dir]

    else:
        raise SandboxError(f"Path {path!r} is not a file or directory.")

    if glob:
        candidates = [
            candidate
            for candidate in candidates
            if _glob_match(
                (
                    candidate.relative_to(base).as_posix()
                    if base.is_dir()
                    else candidate.name
                ),
                glob,
            )
        ]

    pattern = None

    if regex:
        try:
            pattern = re.compile(query)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression: {exc}") from None

    results: list[str] = []

    for candidate in candidates:
        if len(results) >= limit:
            break

        if sandbox.is_protected(candidate):
            continue

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

    if not results:
        return "No matches."

    output = [f"Found {len(results)} " f"match{'es' if len(results) != 1 else ''}:"]

    output.extend(results)

    if len(results) >= limit:
        output.append(
            f"[result limit reached: {limit}; "
            "narrow with path= or glob=, "
            "or increase specificity]"
        )

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
                    "Optional filename or relative-path glob, " "for example '*.py'."
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
