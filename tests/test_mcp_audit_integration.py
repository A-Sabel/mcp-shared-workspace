import json
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from server.audit import audit_tool_call
from server.audited_tool import audited
from server.sandbox import Sandbox
from server.tools import git_tools


def test_registered_tool_writes_audit_record(tmp_path: Path):
    log_path = tmp_path / "tool_calls.jsonl"

    mcp = MCPServer("audit-test")

    @audited(
        tool_name="test_tool",
        role="workspace-client",
        log_path=log_path,
        summarize=lambda args, kwargs: {
            "path": kwargs.get("path"),
        },
    )
    def test_tool(path: str) -> str:
        return f"Read {path}"

    mcp.add_tool(
        test_tool,
        name="test_tool",
        description="Test audited MCP tool.",
        structured_output=False,
    )

    # Verify the MCP server actually registered the tool.
    assert "test_tool" in mcp._tool_manager._tools

    # Call the decorated function through the registered function.
    result = mcp._tool_manager._tools["test_tool"].fn(path="example.txt")

    assert result == "Read example.txt"

    log_text = log_path.read_text(encoding="utf-8")

    assert '"tool":"test_tool"' in log_text
    assert '"client":"workspace-client"' in log_text
    assert '"success":true' in log_text
    assert '"path":"example.txt"' in log_text


def test_registered_tool_logs_failure(tmp_path: Path):
    log_path = tmp_path / "tool_calls.jsonl"

    mcp = MCPServer("audit-failure-test")

    @audited(
        tool_name="failing_tool",
        role="workspace-client",
        log_path=log_path,
        summarize=lambda args, kwargs: {
            "path": kwargs.get("path"),
        },
    )
    def failing_tool(path: str) -> str:
        raise ValueError("Intentional test failure")

    mcp.add_tool(
        failing_tool,
        name="failing_tool",
        description="Test failing audited MCP tool.",
        structured_output=False,
    )

    assert "failing_tool" in mcp._tool_manager._tools

    registered = mcp._tool_manager._tools["failing_tool"].fn

    try:
        registered(path="example.txt")
    except ToolError as exc:
        assert str(exc) == "Intentional test failure"
    else:
        raise AssertionError("Expected ToolError")

    log_text = log_path.read_text(encoding="utf-8")

    assert '"tool":"failing_tool"' in log_text
    assert '"client":"workspace-client"' in log_text
    assert '"success":false' in log_text
    assert "Intentional test failure" in log_text


def test_git_status_and_diff_are_audited_on_failure(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    log_path = tmp_path / "tool_calls.jsonl"
    mcp = MCPServer("git-audit-test")

    git_tools.register(
        mcp,
        Sandbox(workspace),
        "reader",
        log_path,
    )

    for name, arguments in (
        ("git_status", {}),
        ("git_diff", {"path": None}),
    ):
        try:
            mcp._tool_manager._tools[name].fn(**arguments)
        except ToolError as exc:
            assert "not a Git repository" in str(exc)
        else:
            raise AssertionError(f"Expected {name} to fail")

    records = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]

    assert [record["tool"] for record in records] == [
        "git_status",
        "git_diff",
    ]
    assert all(record["success"] is False for record in records)
    assert records[1]["arguments"] == {"path": None}
