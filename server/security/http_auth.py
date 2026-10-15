import logging

from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server.auth.provider import TokenVerifier

from server.security.request_identity import bind_access_token, reset_access_token

logger = logging.getLogger(__name__)


class AuthenticationMiddleware:
    """Authenticate HTTP requests before forwarding them to the MCP app."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        verifier: TokenVerifier,
        resource_metadata_url: str | None = None,
    ) -> None:
        self.app = app
        self.verifier = verifier
        self.resource_metadata_url = resource_metadata_url

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("path") == "/v1/usage/current":
            headers = dict(scope.get("headers", []))
            user_agent = headers.get(b"user-agent", b"").decode("latin-1")[:200]
            client = scope.get("client")
            client_host = client[0] if client else "unknown"
            logger.warning(
                "Request to unsupported /v1/usage/current from %s; User-Agent=%r",
                client_host,
                user_agent or "(missing)",
            )

        authorization = None

        for key, value in scope.get("headers", []):
            if key.lower() == b"authorization":
                authorization = value.decode("latin-1")
                break

        if not authorization:
            await self._unauthorized(send, "Missing Authorization header.")
            return

        scheme, separator, token = authorization.partition(" ")

        if not separator or scheme.lower() != "bearer":
            await self._unauthorized(
                send,
                "Authorization header must use the Bearer scheme.",
            )
            return

        token = token.strip()

        if not token:
            await self._unauthorized(send, "Bearer token is empty.")
            return

        access_token = await self.verifier.verify_token(token)

        if access_token is None:
            await self._unauthorized(send, "Invalid authentication token.")
            return

        if scope.get("path") == "/health" and scope.get("method") == "GET":
            await self._healthy(send)
            return

        context_token = bind_access_token(access_token)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_access_token(context_token)

    async def _unauthorized(self, send: Send, message: str) -> None:
        body = message.encode("utf-8")

        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (
                        b"www-authenticate",
                        (
                            f'Bearer resource_metadata="{self.resource_metadata_url}"'.encode("ascii")
                            if self.resource_metadata_url
                            else b"Bearer"
                        ),
                    ),
                ],
            }
        )

        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )

    @staticmethod
    async def _healthy(send: Send) -> None:
        body = b"ok"

        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )

        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )
