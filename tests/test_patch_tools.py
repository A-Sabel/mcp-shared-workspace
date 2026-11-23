"""Tests for exact-context unified patch application."""

import pytest

from server.sandbox import Sandbox, SandboxError
from server.tools.patch_tools import apply_patch_impl


def test_apply_patch_modifies_file(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1,3 +1,3 @@\n one\n-two\n+TWO\n three\n"
    result = apply_patch_impl(Sandbox(tmp_path), patch)
    assert "a.txt" in result
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "one\nTWO\nthree\n"


def test_context_mismatch_changes_nothing(tmp_path):
    (tmp_path / "a.txt").write_text("actual\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("untouched\n", encoding="utf-8")
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-wrong\n+changed\n"
    with pytest.raises(ValueError, match="Exact context mismatch"):
        apply_patch_impl(Sandbox(tmp_path), patch)
    assert (tmp_path / "a.txt").read_text() == "actual\n"
    assert (tmp_path / "b.txt").read_text() == "untouched\n"


@pytest.mark.parametrize("path", ["../outside.txt", ".env", ".git/config"])
def test_patch_rejects_unsafe_paths(tmp_path, path):
    patch = f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-a\n+b\n"
    with pytest.raises((SandboxError, ValueError)):
        apply_patch_impl(Sandbox(tmp_path), patch)


def test_patch_rejects_rename_and_create(tmp_path):
    with pytest.raises(ValueError, match="Renames"):
        apply_patch_impl(Sandbox(tmp_path), "--- a/a.txt\n+++ b/b.txt\n@@ -1 +1 @@\n-a\n+b\n")
    with pytest.raises(ValueError, match="creation and deletion"):
        apply_patch_impl(Sandbox(tmp_path), "--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+x\n")
