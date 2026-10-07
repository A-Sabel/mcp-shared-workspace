import pytest

from server.security.token_verifier import WorkspaceTokenVerifier

MCP_TOKEN = "mcp-token-123456"


@pytest.mark.anyio
async def test_mcp_token_returns_scoped_access():
    verifier = WorkspaceTokenVerifier(
        mcp_token=MCP_TOKEN,
    )

    result = await verifier.verify_token(MCP_TOKEN)

    assert result is not None
    assert result.subject == "workspace-client"
    assert result.client_id == "workspace-client"
    assert result.claims == {}


@pytest.mark.anyio
async def test_invalid_token_returns_none():
    verifier = WorkspaceTokenVerifier(
        mcp_token=MCP_TOKEN,
    )

    result = await verifier.verify_token("invalid-token")

    assert result is None


def test_mcp_token_is_required():
    with pytest.raises(ValueError, match="required"):
        WorkspaceTokenVerifier(
            mcp_token="",
        )
