"""Tests for Git tools."""

import subprocess

import pytest

from server.sandbox import Sandbox, SandboxError
from server.tools.git_tools import (git_status_impl, git_diff_impl, git_commit_impl, git_log_impl, git_list_branches_impl, git_create_branch_impl, git_switch_branch_impl, git_unstage_impl, git_restore_impl, git_stash_impl)

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


def test_git_log_returns_recent_commit_subject_and_files(git_ws):
    path = git_ws.root / "history.txt"
    path.write_text("first\n", encoding="utf-8")
    git_commit_impl(git_ws, "Add history file", ["history.txt"])
    result = git_log_impl(git_ws, limit=5, include_files=True)
    assert "Add history file" in result
    assert "history.txt" in result
    assert "A" in result


def test_git_log_can_omit_changed_files(git_ws):
    path = git_ws.root / "history.txt"
    path.write_text("first\n", encoding="utf-8")
    git_commit_impl(git_ws, "Add history file", ["history.txt"])
    result = git_log_impl(git_ws, limit=1, include_files=False)
    assert "Add history file" in result
    assert "history.txt" not in result


def test_git_log_rejects_invalid_limit(git_ws):
    with pytest.raises(ValueError, match="limit must be between"):
        git_log_impl(git_ws, limit=0)


def test_git_log_rejects_non_git_workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    with pytest.raises(SandboxError, match="not a Git repository"):
        git_log_impl(Sandbox(root))

def test_git_diff_shows_staged_changes(git_ws):
    path = git_ws.root / "staged.txt"
    path.write_text("staged content\n", encoding="utf-8")
    subprocess.run(["git", "add", "staged.txt"], cwd=git_ws.root, check=True)
    result = git_diff_impl(git_ws, mode="staged")
    assert "staged.txt" in result
    assert "+staged content" in result


def test_git_diff_both_includes_staged_and_unstaged(git_ws):
    path = git_ws.root / "example.txt"
    path.write_text("original\n", encoding="utf-8")
    git_commit_impl(git_ws, "Initial", ["example.txt"])
    path.write_text("staged version\n", encoding="utf-8")
    subprocess.run(["git", "add", "example.txt"], cwd=git_ws.root, check=True)
    path.write_text("unstaged version\n", encoding="utf-8")

    result = git_diff_impl(git_ws, mode="both")

    assert "-original" in result
    assert "+unstaged version" in result


def test_git_diff_rejects_invalid_mode(git_ws):
    with pytest.raises(ValueError, match="mode must be"):
        git_diff_impl(git_ws, mode="all")


def test_git_unstage_changes_index_but_not_worktree(git_ws):
    path = git_ws.root / "file.txt"
    path.write_text("content\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=git_ws.root, check=True)
    git_unstage_impl(git_ws, ["file.txt"])
    status = git_status_impl(git_ws)
    assert "?? file.txt" in status
    assert path.read_text(encoding="utf-8") == "content\n"


def test_git_restore_requires_explicit_confirmation_and_preview(git_ws):
    path = git_ws.root / "file.txt"
    path.write_text("original\n", encoding="utf-8")
    git_commit_impl(git_ws, "initial", ["file.txt"])
    path.write_text("changed\n", encoding="utf-8")
    preview = git_restore_impl(git_ws, ["file.txt"], dry_run=True)
    assert "DRY RUN" in preview
    with pytest.raises(ValueError, match="confirm=true"):
        git_restore_impl(git_ws, ["file.txt"], dry_run=False)
    assert path.read_text(encoding="utf-8") == "changed\n"
    git_restore_impl(git_ws, ["file.txt"], confirm=True, dry_run=False)
    assert path.read_text(encoding="utf-8") == "original\n"


def test_git_restore_never_accepts_workspace_root(git_ws):
    with pytest.raises(ValueError):
        git_restore_impl(git_ws, ["."], confirm=True, dry_run=False)


def test_git_stash_pop_retains_stash_when_apply_conflicts(git_ws):
    path = git_ws.root / "file.txt"
    path.write_text("base\n", encoding="utf-8")
    git_commit_impl(git_ws, "initial", ["file.txt"])
    path.write_text("stashed\n", encoding="utf-8")
    git_stash_impl(git_ws, "push")
    # Create a committed divergent change so the worktree is clean, but
    # applying the stash genuinely produces a content conflict.
    path.write_text("conflicting committed change\n", encoding="utf-8")
    git_commit_impl(git_ws, "conflicting change", ["file.txt"])
    assert "stash@{0}" in git_stash_impl(git_ws, "list")
    with pytest.raises(ValueError, match="stash retained"):
        git_stash_impl(git_ws, "pop")
    assert "stash@{0}" in git_stash_impl(git_ws, "list")


@pytest.mark.parametrize("action", ["apply", "pop"])
def test_git_stash_refuses_to_apply_with_dirty_worktree(git_ws, action):
    stashed = git_ws.root / "stashed.txt"
    local = git_ws.root / "local.txt"
    stashed.write_text("base\n", encoding="utf-8")
    local.write_text("base\n", encoding="utf-8")
    git_commit_impl(git_ws, "initial", ["stashed.txt", "local.txt"])

    stashed.write_text("from stash\n", encoding="utf-8")
    git_stash_impl(git_ws, "push", message="pending change")
    local.write_text("uncommitted local change\n", encoding="utf-8")

    with pytest.raises(ValueError, match="working tree has staged, unstaged, or untracked changes"):
        git_stash_impl(git_ws, action)

    assert local.read_text(encoding="utf-8") == "uncommitted local change\n"
    assert stashed.read_text(encoding="utf-8") == "base\n"
    assert "stash@{0}" in git_stash_impl(git_ws, "list")


def test_git_stash_drop_requires_confirmation(git_ws):
    path = git_ws.root / "file.txt"
    path.write_text("base\n", encoding="utf-8")
    git_commit_impl(git_ws, "initial", ["file.txt"])
    path.write_text("changed\n", encoding="utf-8")
    git_stash_impl(git_ws, "push")
    with pytest.raises(ValueError, match="confirm=true"):
        git_stash_impl(git_ws, "drop")
    assert "stash@{0}" in git_stash_impl(git_ws, "list")
