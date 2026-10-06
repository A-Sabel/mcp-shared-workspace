"""Tests for Git tools."""

import subprocess

import pytest

from server.sandbox import Sandbox, SandboxError
from server.tools.git_tools import git_status_impl, git_diff_impl, git_commit_impl

@pytest.fixture
def git_ws(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()

    subprocess.run(
        ["git", "init"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=root,
        check=True,
        capture_output=True,
    )

    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        check=True,
        capture_output=True,
    )

    return Sandbox(root)


def test_clean_repository_reports_no_worktree_changes(git_ws):
    result = git_status_impl(git_ws)

    assert "##" in result
    assert "??" not in result
    assert " M" not in result
    assert "M " not in result
    assert "A " not in result
    assert " D" not in result
    assert "D " not in result


def test_untracked_file_is_reported(git_ws):
    (git_ws.root / "example.txt").write_text(
        "hello",
        encoding="utf-8",
    )

    result = git_status_impl(git_ws)

    assert "example.txt" in result
    assert "??" in result


def test_modified_file_is_reported(git_ws):
    path = git_ws.root / "example.txt"
    path.write_text(
        "original",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "example.txt"],
        cwd=git_ws.root,
        check=True,
        capture_output=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=git_ws.root,
        check=True,
        capture_output=True,
    )

    path.write_text(
        "modified",
        encoding="utf-8",
    )

    result = git_status_impl(git_ws)

    assert "example.txt" in result
    assert " M" in result


def test_non_git_workspace_is_rejected(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()

    sandbox = Sandbox(root)

    with pytest.raises(SandboxError, match="not a Git repository"):
        git_status_impl(sandbox)

def test_clean_repository_has_no_diff(git_ws):
    result = git_diff_impl(git_ws)

    assert result == "No unstaged changes."


def test_modified_file_appears_in_diff(git_ws):
    path = git_ws.root / "example.txt"
    path.write_text(
        "original\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "example.txt"],
        cwd=git_ws.root,
        check=True,
        capture_output=True,
    )

    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "initial",
        ],
        cwd=git_ws.root,
        check=True,
        capture_output=True,
    )

    path.write_text(
        "modified\n",
        encoding="utf-8",
    )

    result = git_diff_impl(git_ws)

    assert "example.txt" in result
    assert "-original" in result
    assert "+modified" in result


def test_diff_can_be_scoped_to_one_file(git_ws):
    first = git_ws.root / "first.txt"
    second = git_ws.root / "second.txt"

    first.write_text("first\n", encoding="utf-8")
    second.write_text("second\n", encoding="utf-8")

    subprocess.run(
        ["git", "add", "."],
        cwd=git_ws.root,
        check=True,
        capture_output=True,
    )

    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "initial",
        ],
        cwd=git_ws.root,
        check=True,
        capture_output=True,
    )

    first.write_text("first modified\n", encoding="utf-8")
    second.write_text("second modified\n", encoding="utf-8")

    result = git_diff_impl(
        git_ws,
        "first.txt",
    )

    assert "first.txt" in result
    assert "first modified" in result
    assert "second modified" not in result


def test_diff_rejects_path_outside_workspace(git_ws):
    with pytest.raises((SandboxError, ValueError)):
        git_diff_impl(
            git_ws,
            "../outside.txt",
        )


def test_diff_rejects_absolute_path_outside_workspace(git_ws):
    outside = git_ws.root.parent / "outside.txt"

    with pytest.raises((SandboxError, ValueError)):
        git_diff_impl(
            git_ws,
            str(outside),
        )


def test_non_git_workspace_is_rejected_for_diff(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()

    sandbox = Sandbox(root)

    with pytest.raises(
        SandboxError,
        match="not a Git repository",
    ):
        git_diff_impl(sandbox)

def test_commit_explicit_file(git_ws):
    path = git_ws.root / "example.txt"

    path.write_text(
        "hello\n",
        encoding="utf-8",
    )

    result = git_commit_impl(
        git_ws,
        "Add example file",
        ["example.txt"],
    )

    assert "Add example file" in result

    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=git_ws.root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert log.stdout.strip() == "Add example file"


def test_commit_only_selected_paths(git_ws):
    first = git_ws.root / "first.txt"
    second = git_ws.root / "second.txt"

    first.write_text("first\n", encoding="utf-8")
    second.write_text("second\n", encoding="utf-8")

    git_commit_impl(
        git_ws,
        "Add first file",
        ["first.txt"],
    )

    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=git_ws.root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "second.txt" in status.stdout
    assert "first.txt" not in status.stdout


def test_commit_requires_paths(git_ws):
    with pytest.raises(ValueError, match="At least one path"):
        git_commit_impl(
            git_ws,
            "Test commit",
            [],
        )


def test_commit_rejects_empty_message(git_ws):
    with pytest.raises(ValueError, match="must not be empty"):
        git_commit_impl(
            git_ws,
            "",
            ["example.txt"],
        )


def test_commit_rejects_path_traversal(git_ws):
    with pytest.raises(ValueError):
        git_commit_impl(
            git_ws,
            "Malicious commit",
            ["../outside.txt"],
        )


def test_commit_rejects_git_directory(git_ws):
    with pytest.raises(ValueError):
        git_commit_impl(
            git_ws,
            "Modify git internals",
            [".git/config"],
        )


def test_commit_rejects_sensitive_file(git_ws):
    secret = git_ws.root / ".env"
    secret.write_text(
        "SECRET=value\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        git_commit_impl(
            git_ws,
            "Commit secret",
            [".env"],
        )


def test_commit_message_length_is_bounded(git_ws):
    with pytest.raises(ValueError, match="character limit"):
        git_commit_impl(
            git_ws,
            "x" * 201,
            ["example.txt"],
        )


def test_non_git_workspace_is_rejected_for_commit(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()

    sandbox = Sandbox(root)

    with pytest.raises(
        SandboxError,
        match="not a Git repository",
    ):
        git_commit_impl(
            sandbox,
            "Test commit",
            ["example.txt"],
        )