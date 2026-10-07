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
from server.tools import file_tools, search_tools, state_tools, git_tools, write_tools

INSTRUCTIONS = "Shared project workspace. Discover with list_files before reading."


def build_server(settings: Settings) -> MCPServer:
    """Build the authenticated MCP server with all workspace tools."""
    mcp = MCPServer(
        "workspace",
        instructions=INSTRUCTIONS,
    )
    sandbox = Sandbox(settings.workspace_root)
    file_tools.register(mcp, sandbox, log_path=settings.log_path)
    search_tools.register(mcp, sandbox, log_path=settings.log_path)
    state_tools.register(mcp, sandbox, log_path=settings.log_path)
    git_tools.register(mcp, sandbox, log_path=settings.log_path)
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
