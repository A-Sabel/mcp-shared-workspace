from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp
from mcp.server.auth.routes import create_auth_routes, create_protected_resource_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from pydantic import AnyHttpUrl, ConfigDict, TypeAdapter

from server.config import Settings
from server.main import build_server
from server.security.http_auth import AuthenticationMiddleware
from server.security.oauth_provider import WorkspaceOAuthProvider


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
    resource = f"https://{public_hostname}/mcp"
    issuer = f"https://{public_hostname}"
    # RFC 8414 issuer matching is exact; preserve the pathless issuer without
    # Pydantic silently adding a trailing slash.
    issuer_url = TypeAdapter(
        AnyHttpUrl, config=ConfigDict(url_preserve_empty_path=True)
    ).validate_python(issuer)
    provider = WorkspaceOAuthProvider(
        db_path=settings.oauth_db_path or settings.log_path.with_name("oauth.sqlite3"),
        owner_token=settings.mcp_token,
        resource=resource,
    )

    async def sign_in(request: Request) -> HTMLResponse:
        tx = request.query_params.get("tx", "")
        if not tx or len(tx) > 200:
            return HTMLResponse("Invalid or expired sign-in request.", status_code=400)
        if request.method == "GET":
            return HTMLResponse(
                """<!doctype html><html><head><meta name=viewport content='width=device-width'>
                <title>Workspace sign in</title></head><body style='font:16px sans-serif;max-width:32rem;margin:4rem auto'>
                <h1>Sign in to MCP Shared Workspace</h1>
                <p>Enter the workspace access key to authorize Claude.</p>
                <form method=post><input type=hidden name=tx value='""" + tx + """'>
                <label>Workspace access key<br><input type=password name=access_key required autocomplete=current-password
                style='width:100%;padding:.7rem;margin:.5rem 0 1rem'></label>
                <button style='padding:.7rem 1.2rem'>Authorize Claude</button></form></body></html>"""
            )
        form = await request.form()
        form_tx = str(form.get("tx", ""))
        secret = str(form.get("access_key", ""))
        if form_tx != tx:
            return HTMLResponse("Invalid sign-in request.", status_code=400)
        callback = await provider.complete_login(tx, secret)
        if callback is None:
            return HTMLResponse(
                "Invalid access key or expired sign-in request. Close this page and try connecting again.",
                status_code=401,
            )
        return RedirectResponse(callback, status_code=303)

    oauth_routes = create_auth_routes(
        provider,
        issuer_url,
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["workspace"],
            default_scopes=["workspace"],
        ),
        revocation_options=RevocationOptions(enabled=True),
    )
    protected_resource_routes = create_protected_resource_routes(
        AnyHttpUrl(resource),
        [issuer_url],
        scopes_supported=["workspace"],
        resource_name="MCP Shared Workspace",
    )

    # Authentication
    authenticated_app = AuthenticationMiddleware(
        app=mcp_app,
        verifier=provider,
        resource_metadata_url=f"{issuer}/.well-known/oauth-protected-resource/mcp",
    )

    # Parent application lifespan
    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with mcp_server.session_manager.run():
            yield

    # Return host application
    return Starlette(
        routes=[
            *protected_resource_routes,
            *oauth_routes,
            Route("/oauth-login", sign_in, methods=["GET", "POST"]),
            Mount("/", app=authenticated_app),
        ],
        lifespan=lifespan,
    )
