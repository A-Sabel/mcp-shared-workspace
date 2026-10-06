from starlette.testclient import TestClient

from server.security.http_auth import AuthenticationMiddleware
from server.security.token_verifier import WorkspaceTokenVerifier


READER_TOKEN = "reader-token-123456"
WRITER_TOKEN = "writer-token-654321"


def make_test_app():
    async def reader_app(scope, receive, send):
        body = b"reader"

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

    async def writer_app(scope, receive, send):
        body = b"writer"

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
        reader_token=READER_TOKEN,
        writer_token=WRITER_TOKEN,
    )

    return AuthenticationMiddleware(
        reader_app,
        reader_app=reader_app,
        writer_app=writer_app,
        verifier=verifier,
    )


def test_reader_token_routes_to_reader():
    client = TestClient(make_test_app())

    response = client.get(
        "/mcp",
        headers={
            "Authorization": f"Bearer {READER_TOKEN}",
        },
    )

    assert response.status_code == 200
    assert response.text == "reader"


def test_writer_token_routes_to_writer():
    client = TestClient(make_test_app())

    response = client.get(
        "/mcp",
        headers={
            "Authorization": f"Bearer {WRITER_TOKEN}",
        },
    )

    assert response.status_code == 200
    assert response.text == "writer"


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
            "Authorization": f"Basic {READER_TOKEN}",
        },
    )

    assert response.status_code == 401
    assert "Bearer" in response.text