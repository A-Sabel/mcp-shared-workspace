"""Tests for the search_files tool."""

import pytest

from server.sandbox import Sandbox, SandboxError
from server.tools.search_tools import search_files_impl


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "workspace"

    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text(
        "def main():\n"
        "    print('hello')\n"
        "    token = 'abc'\n"
        "    return token\n"
    )
    (root / "src" / "utils.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def authenticate(token):\n"
        "    return token\n"
    )
    (root / "README.md").write_text(
        "# Project\n"
        "This project uses authentication.\n"
    )
    (root / "notes.txt").write_text(
        "one\n"
        "two\n"
        "authentication notes\n"
        "three\n"
    )

    # Protected files/directories.
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text(
        "authentication=secret\n"
    )
    (root / ".env").write_text(
        "TOKEN=secret\n"
    )
    (root / "private.pem").write_text(
        "authentication=secret\n"
    )

    return Sandbox(root)


def test_literal_search_finds_matches(ws):
    result = search_files_impl(ws, "authentication")

    assert "README.md:2:" in result
    assert "notes.txt:3:" in result


def test_search_reports_line_numbers(ws):
    result = search_files_impl(ws, "token")

    assert "src/main.py:3:" in result
    assert "src/main.py:4:" in result
    assert "src/utils.py:5:" in result


def test_search_returns_compact_snippets(ws):
    result = search_files_impl(ws, "authentication")

    for line in result.splitlines():
        if ":2:" in line or ":3:" in line:
            assert len(line) < 200


def test_glob_filters_files(ws):
    result = search_files_impl(
        ws,
        "token",
        glob="*.py",
    )

    assert "src/main.py" in result
    assert "src/utils.py" in result
    assert "README.md" not in result
    assert "notes.txt" not in result


def test_path_restricts_search(ws):
    result = search_files_impl(
        ws,
        "token",
        path="src",
    )

    assert "src/main.py" in result
    assert "src/utils.py" in result
    assert "README.md" not in result


def test_regex_search(ws):
    result = search_files_impl(
        ws,
        r"auth\w+",
        regex=True,
    )

    assert "README.md:2:" in result
    assert "src/utils.py:4:" in result


def test_literal_search_does_not_interpret_regex(ws):
    result = search_files_impl(
        ws,
        r"auth\w+",
        regex=False,
    )

    assert result == "No matches."


def test_limit_bounds_results(ws):
    result = search_files_impl(
        ws,
        "token",
        limit=2,
    )

    assert "src/main.py:3:" in result
    assert "src/main.py:4:" in result
    assert "[result limit reached: 2;" in result


def test_protected_files_are_not_searched(ws):
    result = search_files_impl(
        ws,
        "secret",
    )

    assert ".env" not in result
    assert ".git" not in result
    assert "private.pem" not in result


def test_nonexistent_path_is_rejected(ws):
    with pytest.raises(SandboxError):
        search_files_impl(
            ws,
            "token",
            path="does-not-exist",
        )


def test_empty_query_is_rejected(ws):
    with pytest.raises(ValueError):
        search_files_impl(ws, "")


def test_whitespace_query_is_rejected(ws):
    with pytest.raises(ValueError):
        search_files_impl(ws, "   ")


def test_invalid_regex_is_rejected(ws):
    with pytest.raises(ValueError, match="Invalid regular expression"):
        search_files_impl(
            ws,
            "[invalid",
            regex=True,
        )


def test_invalid_limit_is_rejected(ws):
    with pytest.raises(ValueError):
        search_files_impl(
            ws,
            "token",
            limit=0,
        )


def test_limit_above_configured_max_is_rejected(ws):
    with pytest.raises(ValueError):
        search_files_impl(
            ws,
            "token",
            limit=51,
        )


def test_no_match_is_reported(ws):
    result = search_files_impl(
        ws,
        "definitely-not-present",
    )

    assert result == "No matches."


def test_search_single_file(ws):
    result = search_files_impl(
        ws,
        "token",
        path="src/main.py",
    )

    assert "src/main.py:3:" in result
    assert "src/main.py:4:" in result
    assert "src/utils.py" not in result