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
