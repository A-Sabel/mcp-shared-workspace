"""Tests for symbol navigation tools."""

from server.sandbox import Sandbox
from server.tools.symbol_tools import find_references_impl, find_symbol_impl


def test_python_symbol_definitions_use_ast(tmp_path):
    (tmp_path / "sample.py").write_text("def target():\n    return 1\n\nclass Other:\n    pass\n", encoding="utf-8")
    result = find_symbol_impl(Sandbox(tmp_path), "target")
    assert "sample.py:1: function target" in result


def test_symbol_search_supports_js_declarations(tmp_path):
    (tmp_path / "sample.js").write_text("export function target() {}\nconst other = 1;\n", encoding="utf-8")
    assert "sample.js:1: declaration target" in find_symbol_impl(Sandbox(tmp_path), "target")


def test_references_are_bounded_lexical_matches(tmp_path):
    (tmp_path / "a.py").write_text("target = 1\nprint(target)\nnot_target = 2\n", encoding="utf-8")
    result = find_references_impl(Sandbox(tmp_path), "target")
    assert "a.py:1" in result and "a.py:2" in result
    assert "not_target" not in result
    assert "lexical text matches" in result


def test_invalid_symbol_is_rejected(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="simple identifier"):
        find_symbol_impl(Sandbox(tmp_path), "x; import os")


def test_invalid_symbol_error_echoes_input_and_points_to_search_files(tmp_path):
    import pytest

    for impl in (find_symbol_impl, find_references_impl):
        with pytest.raises(ValueError) as excinfo:
            impl(Sandbox(tmp_path), "pkg.module")

        message = str(excinfo.value)
        assert "'pkg.module'" in message
        assert "search_files" in message


def test_missing_path_suggests_close_name(tmp_path):
    import pytest

    from server.sandbox import SandboxError

    (tmp_path / "src").mkdir()

    for impl in (find_symbol_impl, find_references_impl):
        with pytest.raises(SandboxError, match=r"Did you mean: 'src'\?"):
            impl(Sandbox(tmp_path), "target", path="srcc")


def test_a_single_file_path_is_accepted(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def target():\n    return 1\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("def target():\n    return 2\n", encoding="utf-8")
    sandbox = Sandbox(tmp_path)

    definitions = find_symbol_impl(sandbox, "target", path="src/a.py")
    references = find_references_impl(sandbox, "target", path="src/a.py")

    assert "src/a.py:1: function target" in definitions
    assert "b.py" not in definitions
    assert "FILES SCANNED: 1" in definitions
    assert "src/a.py:1:" in references
    assert "b.py" not in references


def test_protected_file_path_is_rejected(tmp_path):
    import pytest

    from server.sandbox import SandboxError

    (tmp_path / ".env").write_text("target=1\n", encoding="utf-8")

    with pytest.raises(SandboxError):
        find_references_impl(Sandbox(tmp_path), "target", path=".env")


def test_skipped_files_are_reported_and_not_counted_as_scanned(tmp_path):
    (tmp_path / "ok.py").write_text("def target():\n    pass\n", encoding="utf-8")
    (tmp_path / "big.py").write_text("x = 1\n" * 200_000, encoding="utf-8")
    (tmp_path / "bad.py").write_bytes(b"\xff\xfe\x00 not utf-8 \x80\x81")

    result = find_symbol_impl(Sandbox(tmp_path), "target")

    assert "FILES SCANNED: 1" in result
    assert "2 skipped (over 1 MB or not valid UTF-8)" in result
    assert "ok.py:1: function target" in result


def test_no_skip_note_when_every_file_was_read(tmp_path):
    (tmp_path / "ok.py").write_text("def target():\n    pass\n", encoding="utf-8")

    result = find_symbol_impl(Sandbox(tmp_path), "target")

    assert "FILES SCANNED: 1" in result
    assert "skipped" not in result
