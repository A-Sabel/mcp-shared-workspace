"""Server entry point.

    python -m server.main

Runs over stdio for development and MCP Inspector.

stdout is the protocol channel, so nothing here may print to it; diagnostics
go to stderr.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
import sys

from mcp.server.mcpserver import MCPServer

from server.config import ConfigError, Settings, load_settings
from server.sandbox import Sandbox
from server.tools import workspace_tools
from server.workspaces import WorkspaceRegistry

INSTRUCTIONS = (
    "Shared project workspace. Start new project tasks with get_workspace_context "
    "using only the sections needed. Use get_project_map for a compact architecture "
    "overview and get_change_impact before modifying existing code; use "
    "get_file_outline before reading large source files, and "
    "run_project_checks for explicitly allowlisted configured checks. Use apply_patch for "
    "exact-context unified diffs; use find_symbol and find_references for bounded code navigation. "
    "Use git_list_branches and git_create_branch for local branch discovery/creation; "
    "git_switch_branch requires a clean working tree. "
    "Use read_state for bounded handoff history and archive_state before compact_state; "
    "use read_audit_log only when audit details are needed. "
    "Use git_log to inspect recent history. Paths are relative to the active "
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
    tools_dir = Path(__file__).with_name("tools")
    for module_path in sorted(tools_dir.glob("*_tools.py")):
        if module_path.stem == "workspace_tools":
            continue
        module = import_module(f"{__package__}.tools.{module_path.stem}")
        register = getattr(module, "register", None)
        if not callable(register):
            raise TypeError(
                f"Tool module {module_path.name} must define register(mcp, sandbox, log_path=...)."
            )
        register(mcp, sandbox, log_path=settings.log_path)
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
