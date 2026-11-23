"""Server entry point.

    python -m server.main

Runs over stdio for development and MCP Inspector.

stdout is the protocol channel, so nothing here may print to it; diagnostics
go to stderr.
"""

from __future__ import annotations

import sys

from mcp.server.mcpserver import MCPServer

from server.config import ConfigError, Settings, load_settings
from server.sandbox import Sandbox
from server.tools import (
    file_tools,
    git_tools,
    context_tools,
    outline_tools,
    search_tools,
    state_tools,
    write_tools,
    workspace_tools,
)
from server.workspaces import WorkspaceRegistry

INSTRUCTIONS = (
    "Shared project workspace. Start new project tasks with get_workspace_context "
    "using only the sections needed. Use get_file_outline before reading large source "
    "files; use git_log to inspect recent history. Paths are relative to the active "
    "workspace: discover them with list_files before targeted file operations and "
    "never guess filenames. Each read_file range is one-based, inclusive, and limited "
    "to 200 lines. For larger files, start with lines 1-200 and continue using "
    "the returned next_start_line. read_file returns bounded chunks with has_more "
    "and next_start_line; "
    "total_lines may be null unless EOF was reached or counting was requested. "
    "Use your judgment to decide whether a chunk is enough for the task; if you "
    "need more context, request next_start_line; batch up to five known-needed "
    "chunks with read_file ranges when useful. For complete-file requests, "
    "continue until has_more is false. Report any file or range you could not finish."
)


def build_server(settings: Settings) -> MCPServer:
    """Build the authenticated MCP server with all workspace tools."""
    mcp = MCPServer(
        "workspace",
        instructions=INSTRUCTIONS,
    )
    sandbox = Sandbox(settings.workspace_root)
    registry_path = settings.workspace_registry_path or settings.log_path.with_name(
        "workspaces.json"
    )
    registry = WorkspaceRegistry(registry_path, sandbox)
    workspace_tools.register(mcp, registry, settings.log_path)
    file_tools.register(mcp, sandbox, log_path=settings.log_path)
    search_tools.register(mcp, sandbox, log_path=settings.log_path)
    state_tools.register(mcp, sandbox, log_path=settings.log_path)
    git_tools.register(mcp, sandbox, log_path=settings.log_path)
    context_tools.register(mcp, sandbox, log_path=settings.log_path)
    outline_tools.register(mcp, sandbox, log_path=settings.log_path)
    write_tools.register(mcp, sandbox, log_path=settings.log_path)
    return mcp


def main(argv: list[str] | None = None) -> None:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None

    build_server(settings).run(transport="stdio")


if __name__ == "__main__":
    main()
