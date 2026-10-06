"""Tests for the append_state tool."""

import pytest

from server.sandbox import Sandbox, SandboxError
from server.tools.state_tools import (
    HANDOFF_FILES,
    MAX_ENTRY_CHARS,
    append_state_impl,
)


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()

    for filename in HANDOFF_FILES:
        (root / filename).write_text(
            f"# {filename}\n",
            encoding="utf-8",
        )

    return Sandbox(root)


@pytest.mark.parametrize("filename", HANDOFF_FILES)
def test_appends_to_each_handoff_file(ws, filename):
    result = append_state_impl(
        ws,
        filename,
        "Completed the search_files implementation.",
    )

    content = (ws.root / filename).read_text(encoding="utf-8")

    assert "Completed the search_files implementation." in content
    assert filename in result
    assert "UTC" in content


def test_append_preserves_existing_content(ws):
    path = ws.root / "PROJECT_STATE.md"
    original = path.read_text(encoding="utf-8")

    append_state_impl(
        ws,
        "PROJECT_STATE.md",
        "New checkpoint.",
    )

    content = path.read_text(encoding="utf-8")

    assert content.startswith(original)
    assert "New checkpoint." in content


def test_multiple_entries_are_preserved(ws):
    append_state_impl(
        ws,
        "PLAN_LOG.md",
        "First entry.",
    )

    append_state_impl(
        ws,
        "PLAN_LOG.md",
        "Second entry.",
    )

    content = (ws.root / "PLAN_LOG.md").read_text(
        encoding="utf-8"
    )

    assert "First entry." in content
    assert "Second entry." in content


def test_arbitrary_file_is_rejected(ws):
    (ws.root / "notes.md").write_text(
        "do not modify",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Allowed files"):
        append_state_impl(
            ws,
            "notes.md",
            "Should not be written.",
        )


def test_path_traversal_is_rejected(ws):
    with pytest.raises((ValueError, SandboxError)):
        append_state_impl(
            ws,
            "../outside.md",
            "Should not be written.",
        )


def test_empty_entry_is_rejected(ws):
    with pytest.raises(ValueError, match="must not be empty"):
        append_state_impl(
            ws,
            "PROJECT_STATE.md",
            "",
        )


def test_whitespace_entry_is_rejected(ws):
    with pytest.raises(ValueError, match="must not be empty"):
        append_state_impl(
            ws,
            "PROJECT_STATE.md",
            "   ",
        )


def test_entry_size_is_bounded(ws):
    with pytest.raises(ValueError, match="character limit"):
        append_state_impl(
            ws,
            "PROJECT_STATE.md",
            "x" * (MAX_ENTRY_CHARS + 1),
        )


def test_entry_is_stripped(ws):
    append_state_impl(
        ws,
        "CHECKPOINTS.md",
        "   checkpoint complete   ",
    )

    content = (ws.root / "CHECKPOINTS.md").read_text(
        encoding="utf-8"
    )

    assert "checkpoint complete" in content
    assert "   checkpoint complete   " not in content


def test_existing_file_is_not_overwritten(ws):
    path = ws.root / "DECISIONS.md"
    original = path.read_text(encoding="utf-8")

    append_state_impl(
        ws,
        "DECISIONS.md",
        "Use Streamable HTTP.",
    )

    content = path.read_text(encoding="utf-8")

    assert content != original
    assert content.startswith(original)


def test_missing_handoff_file_is_rejected(ws):
    (ws.root / "CHECKPOINTS.md").unlink()

    with pytest.raises((ValueError, SandboxError)):
        append_state_impl(
            ws,
            "CHECKPOINTS.md",
            "Checkpoint.",
        )