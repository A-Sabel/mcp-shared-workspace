from dataclasses import dataclass
from hmac import compare_digest


@dataclass(frozen=True)
class AuthContext:
    """Authenticated MCP client."""

    client_id: str


class AuthenticationError(ValueError):
    """Raised when authentication fails."""


def authenticate_token(
    authorization: str | None,
    *,
    mcp_token: str,
) -> AuthContext:
    """Authenticate a Bearer token."""

    if not authorization:
        raise AuthenticationError("Missing Authorization header.")

    scheme, separator, token = authorization.partition(" ")

    if not separator or scheme.lower() != "bearer":
        raise AuthenticationError("Authorization header must use the Bearer scheme.")

    token = token.strip()

    if not token:
        raise AuthenticationError("Bearer token is empty.")

    if compare_digest(token, mcp_token):
        return AuthContext(client_id="workspace-client")

    raise AuthenticationError("Invalid authentication token.")
