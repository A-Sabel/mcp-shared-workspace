"""Tests for safe local branch operations."""

import subprocess

import pytest

from server.sandbox import Sandbox
from server.tools.git_tools import (
    git_create_branch_impl,
    git_list_branches_impl,
    git_status_impl,
    git_switch_branch_impl,
)


@pytest.fixture
def git_ws(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True)
    return Sandbox(tmp_path)


def _make_initial_commit(sandbox):
    (sandbox.root / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "base.txt"], cwd=sandbox.root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=sandbox.root, check=True, capture_output=True)


def test_branch_create_list_and_switch(git_ws):
    _make_initial_commit(git_ws)
    result = git_create_branch_impl(git_ws, "feature/phase-four")
    assert "current branch was not changed" in result
    assert "feature/phase-four" in git_list_branches_impl(git_ws)
    assert "Switched" in git_switch_branch_impl(git_ws, "feature/phase-four")
    assert "feature/phase-four" in git_status_impl(git_ws)


def test_branch_switch_refuses_dirty_worktree(git_ws):
    _make_initial_commit(git_ws)
    git_create_branch_impl(git_ws, "safe-target")
    (git_ws.root / "local.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(ValueError, match="working tree has"):
        git_switch_branch_impl(git_ws, "safe-target")
    assert (git_ws.root / "local.txt").read_text(encoding="utf-8") == "keep me"


def test_branch_create_rejects_existing_and_invalid_names(git_ws):
    _make_initial_commit(git_ws)
    git_create_branch_impl(git_ws, "already-here")
    with pytest.raises(ValueError, match="already exists"):
        git_create_branch_impl(git_ws, "already-here")
    with pytest.raises(ValueError, match="unsupported|safe Git ref"):
        git_create_branch_impl(git_ws, "../bad")
