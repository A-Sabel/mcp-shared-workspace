import pytest

from server.roles import READER, WRITER
from server.security.auth import (
    AuthContext,
    AuthenticationError,
    authenticate_token,
)


READER_TOKEN = "reader-token-123456"
WRITER_TOKEN = "writer-token-654321"


def test_reader_token_resolves_reader_role():
    result = authenticate_token(
        "Bearer reader-token-123456",
        reader_token=READER_TOKEN,
        writer_token=WRITER_TOKEN,
    )

    assert result == AuthContext(role=READER)


def test_writer_token_resolves_writer_role():
    result = authenticate_token(
        "Bearer writer-token-654321",
        reader_token=READER_TOKEN,
        writer_token=WRITER_TOKEN,
    )

    assert result == AuthContext(role=WRITER)


def test_missing_authorization_is_rejected():
    with pytest.raises(
        AuthenticationError,
        match="Missing Authorization",
    ):
        authenticate_token(
            None,
            reader_token=READER_TOKEN,
            writer_token=WRITER_TOKEN,
        )


def test_wrong_scheme_is_rejected():
    with pytest.raises(
        AuthenticationError,
        match="Bearer",
    ):
        authenticate_token(
            "Basic reader-token-123456",
            reader_token=READER_TOKEN,
            writer_token=WRITER_TOKEN,
        )


def test_empty_bearer_token_is_rejected():
    with pytest.raises(
        AuthenticationError,
        match="empty",
    ):
        authenticate_token(
            "Bearer ",
            reader_token=READER_TOKEN,
            writer_token=WRITER_TOKEN,
        )


def test_invalid_token_is_rejected():
    with pytest.raises(
        AuthenticationError,
        match="Invalid",
    ):
        authenticate_token(
            "Bearer completely-wrong-token",
            reader_token=READER_TOKEN,
            writer_token=WRITER_TOKEN,
        )


def test_tokens_are_not_interchangeable():
    with pytest.raises(AuthenticationError):
        authenticate_token(
            "Bearer reader-token-654321",
            reader_token=READER_TOKEN,
            writer_token=WRITER_TOKEN,
        )


def test_authorization_scheme_is_case_insensitive():
    result = authenticate_token(
        "bearer reader-token-123456",
        reader_token=READER_TOKEN,
        writer_token=WRITER_TOKEN,
    )

    assert result.role == READER