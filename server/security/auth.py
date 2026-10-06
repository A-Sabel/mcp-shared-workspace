from dataclasses import dataclass

from server.roles import READER, WRITER


@dataclass(frozen=True)
class AuthContext:
    """Authenticated identity and application role."""

    role: str


class AuthenticationError(ValueError):
    """Raised when authentication fails."""


def authenticate_token(
    authorization: str | None,
    *,
    reader_token: str,
    writer_token: str,
) -> AuthContext:
    """Authenticate a Bearer token and resolve its application role."""

    if not authorization:
        raise AuthenticationError("Missing Authorization header.")

    scheme, separator, token = authorization.partition(" ")

    if not separator or scheme.lower() != "bearer":
        raise AuthenticationError(
            "Authorization header must use the Bearer scheme."
        )

    token = token.strip()

    if not token:
        raise AuthenticationError("Bearer token is empty.")

    if token == reader_token:
        return AuthContext(role=READER)

    if token == writer_token:
        return AuthContext(role=WRITER)

    raise AuthenticationError("Invalid authentication token.")
