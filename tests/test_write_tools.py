"""Tests for write-oriented file tools."""

import pytest

from server.sandbox import Sandbox, SandboxError
from server.tools.write_tools import (
    delete_file_impl,
    str_replace_impl,
    write_file_impl,
)


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    return Sandbox(root)


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------


def test_write_file_creates_new_file(workspace):
    result = write_file_impl(
        workspace,
        "notes.txt",
        "hello world\n",
    )

    assert "notes.txt" in result
    assert (workspace.root / "notes.txt").read_text(
        encoding="utf-8"
    ) == "hello world\n"


def test_write_file_overwrites_existing_file(workspace):
    path = workspace.root / "notes.txt"
    path.write_text("old content\n", encoding="utf-8")

    result = write_file_impl(
        workspace,
        "notes.txt",
        "new content\n",
    )

    assert "notes.txt" in result
    assert path.read_text(encoding="utf-8") == "new content\n"


def test_write_file_creates_parent_directories(workspace):
    result = write_file_impl(
        workspace,
        "docs/notes.txt",
        "nested file\n",
    )

    path = workspace.root / "docs" / "notes.txt"

    assert "docs/notes.txt" in result
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "nested file\n"


def test_write_file_allows_empty_content(workspace):
    result = write_file_impl(
        workspace,
        "empty.txt",
        "",
    )

    assert "empty.txt" in result
    assert (workspace.root / "empty.txt").read_text(
        encoding="utf-8"
    ) == ""


def test_write_file_rejects_directory_target(workspace):
    directory = workspace.root / "docs"
    directory.mkdir()

    with pytest.raises(ValueError, match="not a regular file"):
        write_file_impl(
            workspace,
            "docs",
            "content",
        )


def test_write_file_rejects_path_traversal(workspace):
    with pytest.raises((SandboxError, ValueError)):
        write_file_impl(
            workspace,
            "../outside.txt",
            "malicious",
        )


def test_write_file_rejects_absolute_path(workspace, tmp_path):
    outside = tmp_path / "outside.txt"

    with pytest.raises((SandboxError, ValueError)):
        write_file_impl(
            workspace,
            str(outside),
            "malicious",
        )


def test_write_file_rejects_protected_file(workspace):
    with pytest.raises((SandboxError, ValueError)):
        write_file_impl(
            workspace,
            ".env",
            "SECRET=value\n",
        )


def test_write_file_rejects_git_directory(workspace):
    git_dir = workspace.root / ".git"
    git_dir.mkdir()

    with pytest.raises((SandboxError, ValueError)):
        write_file_impl(
            workspace,
            ".git/config",
            "malicious",
        )


# ---------------------------------------------------------------------------
# str_replace
# ---------------------------------------------------------------------------


def test_str_replace_replaces_single_match(workspace):
    path = workspace.root / "example.txt"
    path.write_text(
        "hello world\n",
        encoding="utf-8",
    )

    result = str_replace_impl(
        workspace,
        "example.txt",
        "world",
        "MCP",
    )

    assert "1 occurrence" in result
    assert path.read_text(encoding="utf-8") == "hello MCP\n"


def test_str_replace_does_not_replace_multiple_matches_by_default(workspace):
    path = workspace.root / "example.txt"
    path.write_text(
        "hello world\nhello world\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="occurrences"):
        str_replace_impl(
            workspace,
            "example.txt",
            "world",
            "MCP",
        )

    assert path.read_text(encoding="utf-8") == (
        "hello world\nhello world\n"
    )


def test_str_replace_can_replace_all_matches(workspace):
    path = workspace.root / "example.txt"
    path.write_text(
        "hello world\nhello world\n",
        encoding="utf-8",
    )

    result = str_replace_impl(
        workspace,
        "example.txt",
        "world",
        "MCP",
        replace_all=True,
    )

    assert "2 occurrence" in result
    assert path.read_text(encoding="utf-8") == (
        "hello MCP\nhello MCP\n"
    )


def test_str_replace_can_delete_text_with_empty_new_value(workspace):
    path = workspace.root / "example.txt"
    path.write_text(
        "hello world\n",
        encoding="utf-8",
    )

    str_replace_impl(
        workspace,
        "example.txt",
        " world",
        "",
    )

    assert path.read_text(encoding="utf-8") == "hello\n"


def test_str_replace_rejects_missing_text(workspace):
    path = workspace.root / "example.txt"
    path.write_text(
        "hello world\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not found"):
        str_replace_impl(
            workspace,
            "example.txt",
            "missing",
            "replacement",
        )


def test_str_replace_rejects_missing_file(workspace):
    with pytest.raises(ValueError, match="does not exist"):
        str_replace_impl(
            workspace,
            "missing.txt",
            "old",
            "new",
        )


def test_str_replace_rejects_directory(workspace):
    directory = workspace.root / "docs"
    directory.mkdir()

    with pytest.raises(ValueError, match="not a regular file"):
        str_replace_impl(
            workspace,
            "docs",
            "old",
            "new",
        )


def test_str_replace_rejects_path_traversal(workspace):
    with pytest.raises((SandboxError, ValueError)):
        str_replace_impl(
            workspace,
            "../outside.txt",
            "old",
            "new",
        )


def test_str_replace_rejects_protected_file(workspace):
    with pytest.raises((SandboxError, ValueError)):
        str_replace_impl(
            workspace,
            ".env",
            "SECRET",
            "REPLACED",
        )


# ---------------------------------------------------------------------------
# delete_file
# ---------------------------------------------------------------------------


def test_delete_file_moves_file_to_trash(workspace):
    path = workspace.root / "temporary.txt"
    path.write_text(
        "delete me",
        encoding="utf-8",
    )

    result = delete_file_impl(
        workspace,
        "temporary.txt",
    )

    trash_path = (
        workspace.root
        / ".trash"
        / "temporary.txt"
    )

    assert "temporary.txt" in result
    assert not path.exists()
    assert trash_path.exists()
    assert trash_path.read_text(
        encoding="utf-8"
    ) == "delete me"


def test_delete_file_does_not_overwrite_existing_trash_file(
    workspace,
):
    path = workspace.root / "temporary.txt"
    path.write_text(
        "new content",
        encoding="utf-8",
    )

    trash = workspace.root / ".trash"
    trash.mkdir()

    existing = trash / "temporary.txt"
    existing.write_text(
        "old deleted content",
        encoding="utf-8",
    )

    delete_file_impl(
        workspace,
        "temporary.txt",
    )

    new_trash_file = trash / "temporary~1.txt"

    assert existing.read_text(
        encoding="utf-8"
    ) == "old deleted content"

    assert new_trash_file.read_text(
        encoding="utf-8"
    ) == "new content"


def test_delete_file_preserves_nested_path_in_trash(workspace):
    path = (
        workspace.root
        / "src"
        / "utils"
        / "helper.py"
    )

    path.parent.mkdir(parents=True)
    path.write_text(
        "print('hello')\n",
        encoding="utf-8",
    )

    delete_file_impl(
        workspace,
        "src/utils/helper.py",
    )

    trash_path = (
        workspace.root
        / ".trash"
        / "src"
        / "utils"
        / "helper.py"
    )

    assert not path.exists()
    assert trash_path.exists()
    assert trash_path.read_text(
        encoding="utf-8"
    ) == "print('hello')\n"


def test_delete_file_rejects_missing_file(workspace):
    with pytest.raises(ValueError, match="does not exist"):
        delete_file_impl(
            workspace,
            "missing.txt",
        )


def test_delete_file_rejects_directory(workspace):
    directory = workspace.root / "docs"
    directory.mkdir()

    with pytest.raises(ValueError, match="regular files"):
        delete_file_impl(
            workspace,
            "docs",
        )


def test_delete_file_rejects_path_traversal(workspace):
    with pytest.raises((SandboxError, ValueError)):
        delete_file_impl(
            workspace,
            "../outside.txt",
        )


def test_delete_file_rejects_absolute_path(workspace, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("protected", encoding="utf-8")

    with pytest.raises((SandboxError, ValueError)):
        delete_file_impl(
            workspace,
            str(outside),
        )

    assert outside.exists()


def test_delete_file_rejects_protected_file(workspace):
    with pytest.raises((SandboxError, ValueError)):
        delete_file_impl(
            workspace,
            ".env",
        )


def test_delete_file_rejects_git_directory(workspace):
    git_dir = workspace.root / ".git"
    git_dir.mkdir()

    with pytest.raises((SandboxError, ValueError)):
        delete_file_impl(
            workspace,
            ".git/config",
        )