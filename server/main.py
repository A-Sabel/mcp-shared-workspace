"""Server entry point.

    python -m server.main --role reader|writer

Runs over stdio for development and MCP Inspector. The --role flag is a
development convenience only: once the server is reachable over HTTP (M3), the
authenticated token decides the role, never a command-line argument.

stdout is the protocol channel, so nothing here may print to it; diagnostics
go to stderr.
"""

from __future__ import annotations

import argparse
import sys

from mcp.server.mcpserver import MCPServer

from server.config import ConfigError, Settings, load_settings
from server.roles import READER, ROLES
from server.sandbox import Sandbox
from server.tools import file_tools, search_tools, state_tools, git_tools, write_tools

INSTRUCTIONS = "Shared project workspace. Discover with list_files before reading."


def build_server(role: str, settings: Settings) -> MCPServer:
    """Build an MCP server exposing only tools allowed for the role."""
    if role not in ROLES:
        raise ValueError(
            f"Unknown role {role!r}; expected one of {ROLES}."
        )
    mcp = MCPServer(
        f"workspace-{role}",
        instructions=INSTRUCTIONS,
    )
    sandbox = Sandbox(settings.workspace_root)
    file_tools.register(mcp, sandbox, role, settings.log_path)
    search_tools.register(mcp, sandbox, role, settings.log_path)
    state_tools.register(mcp, sandbox, role, settings.log_path)
    git_tools.register(mcp, sandbox, role, settings.log_path)
    write_tools.register(mcp, sandbox, role, settings.log_path)
    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="MCP file server (stdio)")
    parser.add_argument("--role", choices=ROLES, default=READER, help="tool set to expose (default: reader)")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None

    build_server(args.role, settings).run(transport="stdio")


if __name__ == "__main__":
    main()