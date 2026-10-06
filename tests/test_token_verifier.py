import pytest

from server.security.token_verifier import WorkspaceTokenVerifier


READER_TOKEN = "reader-token-123456"
WRITER_TOKEN = "writer-token-654321"


@pytest.mark.anyio
async def test_reader_token_returns_reader_access():
    verifier = WorkspaceTokenVerifier(
        reader_token=READER_TOKEN,
        writer_token=WRITER_TOKEN,
    )

    result = await verifier.verify_token(READER_TOKEN)

    assert result is not None
    assert result.subject == "reader"
    assert result.client_id == "workspace-reader"
    assert result.claims == {"role": "reader"}


@pytest.mark.anyio
async def test_writer_token_returns_writer_access():
    verifier = WorkspaceTokenVerifier(
        reader_token=READER_TOKEN,
        writer_token=WRITER_TOKEN,
    )

    result = await verifier.verify_token(WRITER_TOKEN)

    assert result is not None
    assert result.subject == "writer"
    assert result.client_id == "workspace-writer"
    assert result.claims == {"role": "writer"}


@pytest.mark.anyio
async def test_invalid_token_returns_none():
    verifier = WorkspaceTokenVerifier(
        reader_token=READER_TOKEN,
        writer_token=WRITER_TOKEN,
    )

    result = await verifier.verify_token("invalid-token")

    assert result is None


def test_reader_and_writer_tokens_must_differ():
    with pytest.raises(ValueError, match="must differ"):
        WorkspaceTokenVerifier(
            reader_token=READER_TOKEN,
            writer_token=READER_TOKEN,
        )