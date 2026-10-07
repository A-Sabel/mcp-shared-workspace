import pytest
from server.security.auth import (
    AuthContext,
    AuthenticationError,
    authenticate_token,
)

MCP_TOKEN = "mcp-token-123456"


def test_mcp_token_resolves_granted_scopes():
    result = authenticate_token(
        "Bearer mcp-token-123456",
        mcp_token=MCP_TOKEN,
    )

    assert result == AuthContext(client_id="workspace-client")


def test_missing_authorization_is_rejected():
    with pytest.raises(
        AuthenticationError,
        match="Missing Authorization",
    ):
        authenticate_token(
            None,
            mcp_token=MCP_TOKEN,
        )


def test_wrong_scheme_is_rejected():
    with pytest.raises(
        AuthenticationError,
        match="Bearer",
    ):
        authenticate_token(
            "Basic mcp-token-123456",
            mcp_token=MCP_TOKEN,
        )


def test_empty_bearer_token_is_rejected():
    with pytest.raises(
        AuthenticationError,
        match="empty",
    ):
        authenticate_token(
            "Bearer ",
            mcp_token=MCP_TOKEN,
        )


def test_invalid_token_is_rejected():
    with pytest.raises(
        AuthenticationError,
        match="Invalid",
    ):
        authenticate_token(
            "Bearer completely-wrong-token",
            mcp_token=MCP_TOKEN,
        )


def test_old_token_is_rejected():
    with pytest.raises(AuthenticationError):
        authenticate_token(
            "Bearer old-token",
            mcp_token=MCP_TOKEN,
        )


def test_authorization_scheme_is_case_insensitive():
    result = authenticate_token(
        "bearer mcp-token-123456",
        mcp_token=MCP_TOKEN,
    )

    assert result.client_id == "workspace-client"
