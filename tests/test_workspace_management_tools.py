from pathlib import Path

from starlette.testclient import TestClient

from tests.test_streamable_http import (
    MCP_TOKEN,
    call_tool,
    initialize_session,
    make_settings,
)
from server.http_app import build_http_app


def _tool_text(result: dict) -> str:
    return result["content"][0]["text"]


def test_workspace_management_tools_round_trip(tmp_path: Path):
    settings = make_settings(tmp_path)
    app = build_http_app(settings)

    with TestClient(app) as client:
        session_id = initialize_session(client, MCP_TOKEN)

        created = call_tool(
            client, MCP_TOKEN, session_id, "create_directory",
            {"path": "notes/archive"},
        )
        assert "Directory ready" in _tool_text(created)

        written = call_tool(
            client, MCP_TOKEN, session_id, "write_file",
            {"path": "notes/draft.md", "content": "workspace note"},
        )
        assert "Wrote" in _tool_text(written)

        moved = call_tool(
            client, MCP_TOKEN, session_id, "move_file",
            {"source": "notes/draft.md", "destination": "notes/archive/final.md"},
        )
        assert "Moved" in _tool_text(moved)
        assert (settings.workspace_root / "notes/archive/final.md").read_text() == "workspace note"

        call_tool(
            client, MCP_TOKEN, session_id, "append_state",
            {"file": "PLAN_LOG.md", "entry": "Completed the workspace management milestone."},
        )
        recent = call_tool(
            client, MCP_TOKEN, session_id, "read_state",
            {"file": "PLAN_LOG.md", "limit": 1},
        )
        assert "Completed the workspace management milestone." in _tool_text(recent)

        archived = call_tool(
            client, MCP_TOKEN, session_id, "archive_state",
            {"file": "PLAN_LOG.md"},
        )
        assert "Archived PLAN_LOG.md" in _tool_text(archived)

        compacted = call_tool(
            client, MCP_TOKEN, session_id, "compact_state",
            {"file": "PLAN_LOG.md", "summary": "# Plan Log\n\nCurrent status: complete."},
        )
        assert "full prior contents preserved" in _tool_text(compacted)
        assert "Current status: complete." in (settings.workspace_root / "PLAN_LOG.md").read_text()

        audit = call_tool(
            client, MCP_TOKEN, session_id, "read_audit_log",
            {"limit": 20},
        )
        assert "move_file" in _tool_text(audit)
        assert "compact_state" in _tool_text(audit)
