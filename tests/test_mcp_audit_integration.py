from pathlib import Path

from mcp.server.mcpserver import MCPServer

from server.audit import audit_tool_call
from server.audited_tool import audited


def test_registered_tool_writes_audit_record(tmp_path: Path):
    log_path = tmp_path / "tool_calls.jsonl"

    mcp = MCPServer("audit-test")

    @audited(
        tool_name="test_tool",
        role="reader",
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
    result = mcp._tool_manager._tools["test_tool"].fn(
        path="example.txt"
    )

    assert result == "Read example.txt"

    log_text = log_path.read_text(encoding="utf-8")

    assert '"tool":"test_tool"' in log_text
    assert '"role":"reader"' in log_text
    assert '"success":true' in log_text
    assert '"path":"example.txt"' in log_text


def test_registered_tool_logs_failure(tmp_path: Path):
    log_path = tmp_path / "tool_calls.jsonl"

    mcp = MCPServer("audit-failure-test")

    @audited(
        tool_name="failing_tool",
        role="writer",
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
    except ValueError as exc:
        assert str(exc) == "Intentional test failure"
    else:
        raise AssertionError("Expected ValueError")

    log_text = log_path.read_text(encoding="utf-8")

    assert '"tool":"failing_tool"' in log_text
    assert '"role":"writer"' in log_text
    assert '"success":false' in log_text
    assert "Intentional test failure" in log_text
