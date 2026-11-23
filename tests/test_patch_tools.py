"""Tests for exact-context unified patch application."""

import hashlib

import pytest

from server.sandbox import Sandbox, SandboxError
from server.tools.patch_tools import apply_patch_impl


def test_apply_patch_modifies_file(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1,3 +1,3 @@\n one\n-two\n+TWO\n three\n"
    result = apply_patch_impl(Sandbox(tmp_path), patch)
    assert "a.txt" in result
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "one\nTWO\nthree\n"


def test_apply_patch_accepts_git_headers_fences_and_blank_context(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("before\n\nold\nafter\n", encoding="utf-8")
    fence = chr(96) * 3
    patch = "\n".join(
        [
            fence + "diff",
            "diff --git a/a.txt b/a.txt",
            "index 1111111..2222222 100644",
            "--- a/a.txt",
            "+++ b/a.txt",
            "@@ -1,4 +1,4 @@",
            " before",
            "",
            "-old",
            "+new",
            " after",
            fence,
        ]
    )

    apply_patch_impl(Sandbox(tmp_path), patch)

    assert target.read_text(encoding="utf-8") == "before\n\nnew\nafter\n"


def test_patch_parser_reports_invalid_hunk_line_content(tmp_path):
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\noops\n"

    with pytest.raises(ValueError, match=r"Invalid hunk line at patch line 4: 'oops'.*leading space"):
        apply_patch_impl(Sandbox(tmp_path), patch)


def test_patch_parser_reports_hunk_number_and_counts(tmp_path):
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1,2 +1,2 @@\n-old\n+new\n"

    with pytest.raises(ValueError, match=r"Hunk 1 .*declares 2 old/2 new lines, found 1 old/1 new"):
        apply_patch_impl(Sandbox(tmp_path), patch)


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


def test_apply_patch_rejects_stale_expected_hash(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("one\ntwo\n", encoding="utf-8")
    stale_hash = hashlib.sha256(b"old content").hexdigest()
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1,2 +1,2 @@\n one\n-two\n+TWO\n"

    with pytest.raises(ValueError, match="Concurrency conflict"):
        apply_patch_impl(Sandbox(tmp_path), patch, expected_hash=stale_hash)

    assert target.read_text(encoding="utf-8") == "one\ntwo\n"


def test_apply_patch_accepts_current_expected_hash(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("one\ntwo\n", encoding="utf-8")
    current_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1,2 +1,2 @@\n one\n-two\n+TWO\n"

    apply_patch_impl(Sandbox(tmp_path), patch, expected_hash=current_hash)
    assert target.read_text(encoding="utf-8") == "one\nTWO\n"


def test_apply_patch_requires_hash_for_every_file_when_mapping_supplied(tmp_path):
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text("old\n", encoding="utf-8")
    patch = (
        "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"
        "--- a/b.txt\n+++ b/b.txt\n@@ -1 +1 @@\n-old\n+new\n"
    )

    with pytest.raises(ValueError, match="exactly one"):
        apply_patch_impl(Sandbox(tmp_path), patch, expected_hashes={"a.txt": "0" * 64})


def test_apply_patch_rejects_expected_hash_for_multi_file_patch(tmp_path):
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text("old\n", encoding="utf-8")
    patch = (
        "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"
        "--- a/b.txt\n+++ b/b.txt\n@@ -1 +1 @@\n-old\n+new\n"
    )

    with pytest.raises(ValueError, match="single-file"):
        apply_patch_impl(Sandbox(tmp_path), patch, expected_hash="0" * 64)


def test_multi_file_patch_rolls_back_when_a_swap_fails(tmp_path, monkeypatch):
    import server.tools.patch_tools as patch_module

    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("old-a\n", encoding="utf-8")
    b.write_text("old-b\n", encoding="utf-8")
    patch = (
        "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old-a\n+new-a\n"
        "--- a/b.txt\n+++ b/b.txt\n@@ -1 +1 @@\n-old-b\n+new-b\n"
    )
    real_replace = patch_module.os.replace
    calls = 0

    def fail_second_swap(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected swap failure")
        return real_replace(source, target)

    monkeypatch.setattr(patch_module.os, "replace", fail_second_swap)
    with pytest.raises(OSError, match="injected swap failure"):
        apply_patch_impl(Sandbox(tmp_path), patch)
    assert a.read_text(encoding="utf-8") == "old-a\n"
    assert b.read_text(encoding="utf-8") == "old-b\n"
