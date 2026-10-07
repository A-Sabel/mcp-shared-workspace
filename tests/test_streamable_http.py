import json
from pathlib import Path

from starlette.testclient import TestClient


from server.config import Settings
from server.http_app import build_http_app

MCP_TOKEN = "mcp-token-123456"


def make_settings(
    tmp_path: Path,
) -> Settings:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    return Settings(
        workspace_root=workspace,
        mcp_token=MCP_TOKEN,
        log_path=tmp_path / "tool_calls.jsonl",
    )


def initialize_request():
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {
                "name": "pytest-client",
                "version": "1.0",
            },
        },
    }


def post_mcp(client: TestClient, token: str, payload: dict):
    return client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json=payload,
    )


def extract_json(response) -> dict:
    """Extract the JSON-RPC message from either JSON or SSE output."""

    content_type = response.headers.get("content-type", "")

    if "application/json" in content_type:
        return response.json()

    text = response.text

    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())

    raise AssertionError(f"Could not find JSON-RPC response in response body: {text!r}")


def initialize_session(client: TestClient, token: str) -> str:
    response = post_mcp(
        client,
        token,
        initialize_request(),
    )

    assert response.status_code == 200

    session_id = response.headers.get("mcp-session-id")

    assert session_id, "Streamable HTTP server did not return an MCP session ID."

    initialize_result = extract_json(response)

    assert initialize_result["jsonrpc"] == "2.0"
    assert initialize_result["id"] == 1
    assert "result" in initialize_result

    return session_id


def list_tools(
    client: TestClient,
    token: str,
    session_id: str,
):
    response = client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Mcp-Session-Id": session_id,
        },
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        },
    )

    assert response.status_code == 200

    result = extract_json(response)

    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 2
    assert "result" in result

    return result["result"]["tools"]


def call_tool(
    client: TestClient,
    token: str,
    session_id: str,
    name: str,
    arguments: dict,
):
    response = client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Mcp-Session-Id": session_id,
        },
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments,
            },
        },
    )

    assert response.status_code == 200

    result = extract_json(response)

    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 3
    assert "result" in result

    return result["result"]


def test_tool_call_returns_content_and_error_flag(tmp_path: Path):
    settings = make_settings(tmp_path)
    app = build_http_app(settings)

    with TestClient(app) as client:
        session_id = initialize_session(client, MCP_TOKEN)

        success = call_tool(
            client,
            MCP_TOKEN,
            session_id,
            "list_files",
            {"path": "."},
        )

        assert success["content"]
        assert success["content"][0]["type"] == "text"
        assert success.get("isError", False) is False

        failure = call_tool(
            client,
            MCP_TOKEN,
            session_id,
            "read_file",
            {
                "ranges": [
                    {
                        "path": "missing.txt",
                        "start": 1,
                        "end": 1,
                    }
                ],
            },
        )

        assert failure["content"]
        assert failure["content"][0]["type"] == "text"
        assert "missing.txt" in failure["content"][0]["text"]
        assert failure["isError"] is True


def test_append_state_schema_exposes_handoff_file_enum(tmp_path: Path):
    settings = make_settings(tmp_path)
    app = build_http_app(settings)

    with TestClient(app) as client:
        session_id = initialize_session(client, MCP_TOKEN)
        tools = list_tools(client, MCP_TOKEN, session_id)

    append_state = next(tool for tool in tools if tool["name"] == "append_state")
    file_schema = append_state["inputSchema"]["properties"]["file"]

    assert file_schema["enum"] == [
        "PROJECT_STATE.md",
        "PLAN_LOG.md",
        "CHECKPOINTS.md",
        "DECISIONS.md",
    ]


def test_authenticated_client_sees_all_tools(tmp_path: Path):
    settings = make_settings(tmp_path)
    app = build_http_app(settings)

    with TestClient(app) as client:
        session_id = initialize_session(
            client,
            MCP_TOKEN,
        )

        tools = list_tools(
            client,
            MCP_TOKEN,
            session_id,
        )

        names = {tool["name"] for tool in tools}

        expected_tools = {
            "list_files",
            "read_file",
            "search_files",
            "append_state",
            "git_status",
            "git_diff",
            "write_file",
            "str_replace",
            "delete_file",
            "git_commit",
        }

        assert names == expected_tools


def test_invalid_token_cannot_initialize(tmp_path: Path):
    settings = make_settings(tmp_path)
    app = build_http_app(settings)

    with TestClient(app) as client:
        response = post_mcp(
            client,
            "invalid-token",
            initialize_request(),
        )

        assert response.status_code == 401


def test_missing_token_cannot_initialize(tmp_path: Path):
    settings = make_settings(tmp_path)
    app = build_http_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json=initialize_request(),
        )

        assert response.status_code == 401
