from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import ASGIApp

from server.config import Settings
from server.main import build_server
from server.security.http_auth import AuthenticationMiddleware
from server.security.token_verifier import WorkspaceTokenVerifier


# Public hostname currently assigned by ngrok.
# If the ngrok URL changes, update this value.
NGROK_HOST = "virtuous-promptly-petition.ngrok-free.dev"


def build_http_app(settings: Settings) -> ASGIApp:
    """
    Build the authenticated Streamable HTTP application.

    Two separate MCPServer instances are used:
      - reader_server exposes reader tools only
      - writer_server exposes reader + writer tools

    Authentication middleware chooses which server receives
    each request based on the Bearer token.
    """

    # Create role-specific MCP servers
    reader_server = build_server("reader", settings)
    writer_server = build_server("writer", settings)

    # Transport security
    # Allow:
    #   - Starlette TestClient
    #   - the current ngrok hostname
    # We keep an explicit allowlist instead of disabling
    # DNS-rebinding protection.

    transport_security = TransportSecuritySettings(
        allowed_hosts=[
            "testserver",
            "testserver:*",
            NGROK_HOST,
            f"{NGROK_HOST}:*",
        ],
        allowed_origins=[
            "http://testserver",
            f"https://{NGROK_HOST}",
        ],
    )

    # Create Streamable HTTP applications
    reader_app = reader_server.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=transport_security,
        host="testserver",
    )

    writer_app = writer_server.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=transport_security,
        host="testserver",
    )

    # Token verifier
    verifier = WorkspaceTokenVerifier(
        reader_token=settings.reader_token,
        writer_token=settings.writer_token,
        resource=f"https://{NGROK_HOST}/mcp",
    )

    # Authentication + role routing
    authenticated_app = AuthenticationMiddleware(
        app=reader_app,
        reader_app=reader_app,
        writer_app=writer_app,
        verifier=verifier,
    )

    # Parent application lifespan
    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        reader_manager = reader_server.session_manager
        writer_manager = writer_server.session_manager

        async with reader_manager.run():
            async with writer_manager.run():
                yield

    # Return host application
    return Starlette(
        routes=[
            Mount("/", app=authenticated_app),
        ],
        lifespan=lifespan,
    )