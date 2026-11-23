"""Tests for compact workspace context retrieval."""

import subprocess

import pytest

from server.sandbox import Sandbox
from server.tools.context_tools import get_workspace_context_impl


def test_context_includes_selected_sections(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("Use pytest.\n", encoding="utf-8")
    (root / "PROJECT_STATE.md").write_text("Current milestone: tools.\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")

    result = get_workspace_context_impl(
        Sandbox(root),
        ["project_structure", "project_instructions", "project_state", "recent_changes"],
        1000,
    )

    assert "src/main.py" in result
    assert "Use pytest." in result
    assert "Current milestone: tools." in result
    assert "Recent Changes" in result


def test_context_rejects_unknown_section(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    with pytest.raises(ValueError, match="Unknown context section"):
        get_workspace_context_impl(Sandbox(root), ["everything"])


def test_context_enforces_token_budget(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    with pytest.raises(ValueError, match="max_tokens"):
        get_workspace_context_impl(Sandbox(root), ["project_structure"], 10000)


def test_context_does_not_include_protected_files(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    (root / ".env").write_text("SECRET=do-not-leak", encoding="utf-8")
    (root / "visible.txt").write_text("visible", encoding="utf-8")
    result = get_workspace_context_impl(Sandbox(root), ["project_structure"], 500)
    assert "visible.txt" in result
    assert ".env" not in result
    assert "do-not-leak" not in result
