from mcp.server.auth.provider import AccessToken


class WorkspaceTokenVerifier:
    """Verify the shared-workspace reader and writer bearer tokens."""

    def __init__(
        self,
        *,
        reader_token: str,
        writer_token: str,
        resource: str | None = None,
    ) -> None:
        if not reader_token or not writer_token:
            raise ValueError("Reader and writer tokens are required.")

        if reader_token == writer_token:
            raise ValueError("Reader and writer tokens must differ.")

        self.reader_token = reader_token
        self.writer_token = writer_token
        self.resource = resource

    async def verify_token(
        self,
        token: str,
    ) -> AccessToken | None:
        """Return MCP access information for a valid workspace token."""

        if token == self.reader_token:
            return AccessToken(
                token=token,
                client_id="workspace-reader",
                scopes=["workspace"],
                resource=self.resource,
                subject="reader",
                claims={
                    "role": "reader",
                },
            )

        if token == self.writer_token:
            return AccessToken(
                token=token,
                client_id="workspace-writer",
                scopes=["workspace"],
                resource=self.resource,
                subject="writer",
                claims={
                    "role": "writer",
                },
            )

        return None