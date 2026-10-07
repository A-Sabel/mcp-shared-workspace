from starlette.types import ASGIApp, Receive, Scope, Send

from server.security.token_verifier import WorkspaceTokenVerifier


class AuthenticationMiddleware:
    """Authenticate HTTP requests before forwarding them to the MCP app."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        verifier: WorkspaceTokenVerifier,
    ) -> None:
        self.app = app
        self.verifier = verifier

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

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

        await self.app(scope, receive, send)

    @staticmethod
    async def _unauthorized(send: Send, message: str) -> None:
        body = message.encode("utf-8")

        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"www-authenticate", b"Bearer"),
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
