import json
from pathlib import Path

from starlette.testclient import TestClient


from server.config import Settings
from server.http_app import build_http_app
from server.roles import READER, WRITER

READER_TOKEN = "reader-token-123456"
WRITER_TOKEN = "writer-token-654321"


def make_settings(tmp_path: Path) -> Settings:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    return Settings(
        workspace_root=workspace,
        reader_token=READER_TOKEN,
        writer_token=WRITER_TOKEN,
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


def test_reader_can_initialize_and_only_sees_reader_tools(tmp_path: Path):
    settings = make_settings(tmp_path)
    app = build_http_app(settings)

    with TestClient(app) as client:
        session_id = initialize_session(
            client,
            READER_TOKEN,
        )

        tools = list_tools(
            client,
            READER_TOKEN,
            session_id,
        )

        names = {tool["name"] for tool in tools}

        expected_reader_tools = {
            "list_files",
            "read_file",
            "search_files",
            "append_state",
            "git_status",
            "git_diff",
        }

        assert names == expected_reader_tools

        assert "write_file" not in names
        assert "str_replace" not in names
        assert "delete_file" not in names
        assert "git_commit" not in names


def test_writer_can_initialize_and_sees_all_tools(tmp_path: Path):
    settings = make_settings(tmp_path)
    app = build_http_app(settings)

    with TestClient(app) as client:
        session_id = initialize_session(
            client,
            WRITER_TOKEN,
        )

        tools = list_tools(
            client,
            WRITER_TOKEN,
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
