from hmac import compare_digest

from mcp.server.auth.provider import AccessToken


class WorkspaceTokenVerifier:
    """Verify the shared-workspace bearer token."""

    def __init__(
        self,
        *,
        mcp_token: str,
        resource: str | None = None,
    ) -> None:
        if not mcp_token:
            raise ValueError("MCP token is required.")
        self.mcp_token = mcp_token
        self.resource = resource

    async def verify_token(
        self,
        token: str,
    ) -> AccessToken | None:
        """Return MCP access information for a valid workspace token."""

        if compare_digest(token, self.mcp_token):
            return AccessToken(
                token=token,
                client_id="workspace-client",
                scopes=["workspace"],
                resource=self.resource,
                subject="workspace-client",
                claims={},
            )

        return None
