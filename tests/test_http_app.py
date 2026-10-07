from starlette.testclient import TestClient

from server.security.http_auth import AuthenticationMiddleware
from server.security.token_verifier import WorkspaceTokenVerifier

MCP_TOKEN = "mcp-token-123456"


def make_test_app():
    async def mcp_app(scope, receive, send):
        body = b"mcp"

        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/plain"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )

        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )

    verifier = WorkspaceTokenVerifier(
        mcp_token=MCP_TOKEN,
    )

    return AuthenticationMiddleware(
        mcp_app,
        verifier=verifier,
    )


def test_authenticated_token_forwards_to_mcp_app():
    client = TestClient(make_test_app())

    response = client.get(
        "/mcp",
        headers={
            "Authorization": f"Bearer {MCP_TOKEN}",
        },
    )

    assert response.status_code == 200
    assert response.text == "mcp"


def test_authenticated_health_check_returns_ok():
    client = TestClient(make_test_app())

    response = client.get(
        "/health",
        headers={
            "Authorization": f"Bearer {MCP_TOKEN}",
        },
    )

    assert response.status_code == 200
    assert response.text == "ok"


def test_missing_token_returns_401():
    client = TestClient(make_test_app())

    response = client.get("/mcp")

    assert response.status_code == 401
    assert "Missing Authorization" in response.text


def test_invalid_token_returns_401():
    client = TestClient(make_test_app())

    response = client.get(
        "/mcp",
        headers={
            "Authorization": "Bearer invalid-token",
        },
    )

    assert response.status_code == 401
    assert "Invalid authentication token" in response.text


def test_wrong_auth_scheme_returns_401():
    client = TestClient(make_test_app())

    response = client.get(
        "/mcp",
        headers={
            "Authorization": f"Basic {MCP_TOKEN}",
        },
    )

    assert response.status_code == 401
    assert "Bearer" in response.text
