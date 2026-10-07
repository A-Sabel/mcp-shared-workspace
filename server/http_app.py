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


def build_http_app(settings: Settings) -> ASGIApp:
    """
    Build the authenticated Streamable HTTP application.

        One MCPServer instance exposes the complete authenticated toolbox.
    """

    mcp_server = build_server(settings)

    # Transport security
    # Allow:
    #   - Starlette TestClient
    #   - the current ngrok hostname
    # We keep an explicit allowlist instead of disabling
    # DNS-rebinding protection.

    public_hostname = settings.public_hostname

    transport_security = TransportSecuritySettings(
        allowed_hosts=[
            "testserver",
            "testserver:*",
            public_hostname,
            f"{public_hostname}:*",
        ],
        allowed_origins=[
            "http://testserver",
            f"https://{public_hostname}",
        ],
    )

    # Create Streamable HTTP applications
    mcp_app = mcp_server.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=transport_security,
        host="testserver",
    )

    # Token verifier
    verifier = WorkspaceTokenVerifier(
        mcp_token=settings.mcp_token,
        resource=f"https://{public_hostname}/mcp",
    )

    # Authentication + role routing
    authenticated_app = AuthenticationMiddleware(
        app=mcp_app,
        verifier=verifier,
    )

    # Parent application lifespan
    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with mcp_server.session_manager.run():
            yield

    # Return host application
    return Starlette(
        routes=[
            Mount("/", app=authenticated_app),
        ],
        lifespan=lifespan,
    )
