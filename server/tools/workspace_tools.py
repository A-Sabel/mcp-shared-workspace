"""MCP tools for registering and selecting named workspaces."""

from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from server.audited_tool import audited
from server.workspaces import WorkspaceRegistry


def _summary(_args, kwargs):
    return {key: value for key, value in kwargs.items() if key == "name"}


def register(mcp: MCPServer, registry: WorkspaceRegistry, log_path: Path) -> None:
    @audited(tool_name="list_workspaces", role="workspace-client", log_path=log_path, summarize=lambda _a, _k: {})
    def list_workspaces() -> str:
        """List registered workspaces and identify the active one."""
        return registry.list()

    @audited(tool_name="register_workspace", role="workspace-client", log_path=log_path, summarize=_summary)
    def register_workspace(
        name: Annotated[str, Field(min_length=1, max_length=64, description="Short unique name for this workspace.")],
        path: Annotated[str, Field(min_length=1, max_length=4096, description="Absolute path to an existing project directory.")],
    ) -> str:
        """Register an existing project directory for later switching."""
        return registry.register(name, path)

    @audited(tool_name="switch_workspace", role="workspace-client", log_path=log_path, summarize=_summary)
    def switch_workspace(
        name: Annotated[str, Field(min_length=1, max_length=64, description="Name returned by list_workspaces.")],
    ) -> str:
        """Switch all workspace file tools to a registered project directory."""
        return registry.switch(name)

    mcp.add_tool(list_workspaces, name="list_workspaces", structured_output=False)
    mcp.add_tool(register_workspace, name="register_workspace", structured_output=False)
    mcp.add_tool(switch_workspace, name="switch_workspace", structured_output=False)
