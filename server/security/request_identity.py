"""Per-request identity helpers for authenticated MCP calls."""

from __future__ import annotations

from contextvars import ContextVar, Token

from mcp.server.auth.provider import AccessToken

_CURRENT_ACCESS_TOKEN: ContextVar[AccessToken | None] = ContextVar(
    "workspace_access_token", default=None
)


def bind_access_token(access_token: AccessToken) -> Token:
    """Bind the verified request token while its MCP request is handled."""
    return _CURRENT_ACCESS_TOKEN.set(access_token)


def reset_access_token(token: Token) -> None:
    """Restore the prior request identity after handling the request."""
    _CURRENT_ACCESS_TOKEN.reset(token)


def current_audit_identity(fallback: str) -> str:
    """Identify the authenticated MCP client without recording role data."""
    access_token = _CURRENT_ACCESS_TOKEN.get()
    if access_token is None:
        return fallback
    return access_token.client_id or fallback
