"""Tests for static change-impact analysis."""

import pytest

from server.sandbox import Sandbox, SandboxError
from server.tools.change_impact_tools import get_change_impact_impl


def test_change_impact_reports_importers_symbol_references_and_tests(tmp_path):
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "service.py").write_text(
        "def calculate_total(value):\n    return value * 2\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (root / "app" / "api.py").write_text(
        "from app.service import calculate_total\n\ndef endpoint(x):\n    return calculate_total(x)\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_service.py").write_text(
        "from app.service import calculate_total\n\ndef test_total():\n    assert calculate_total(2) == 4\n",
        encoding="utf-8",
    )

    result = get_change_impact_impl(Sandbox(root), "app/service.py")

    assert "DIRECT IMPORTS:" in result
    assert "LIKELY DEPENDENTS (2)" in result
    assert "app/api.py" in result
    assert "tests/test_service.py" in result
    assert "calculate_total" in result
    assert "RELATED TESTS (1)" in result
    assert "RELEVANT ROOT CONFIGURATION (1)" in result
    assert "pyproject.toml" in result
    assert "CURRENT GIT STATUS:" in result
    assert "Static heuristic only" in result


def test_change_impact_can_search_for_a_symbol(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()

def test_change_impact_extracts_javascript_symbols(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "service.js").write_text(
        "export function normalizeInput(value) { return value.trim(); }\\n",
        encoding="utf-8",
    )
    (root / "tests" / "service.test.js").write_text(
        "normalizeInput(' x ');\\n",
        encoding="utf-8",
    )

    result = get_change_impact_impl(Sandbox(root), "src/service.js")

    assert "normalizeInput" in result
    assert "service.test.js" in result
    assert "RELATED TESTS (1)" in result

    (root / "src" / "logic.py").write_text(
        "def normalize_input(value):\n    return value.strip()\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_logic.py").write_text(
        "assert normalize_input(' x ') == 'x'\n",
        encoding="utf-8",
    )

    result = get_change_impact_impl(Sandbox(root), "normalize_input")

    assert "TARGET TYPE: symbol/name search" in result
    assert "tests/test_logic.py" in result
    assert "RELATED TESTS (1)" in result


def test_change_impact_respects_file_and_result_limits(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    for index in range(4):
        (root / f"module{index}.py").write_text("import os\n", encoding="utf-8")

    result = get_change_impact_impl(
        Sandbox(root), "module0.py", max_files=1, max_results=1
    )
    assert "file limit reached" in result


def test_change_impact_rejects_invalid_targets_options_and_paths(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sandbox = Sandbox(root)

    with pytest.raises(ValueError, match="target"):
        get_change_impact_impl(sandbox, " ")
    with pytest.raises(ValueError, match="max_files"):
        get_change_impact_impl(sandbox, "thing", max_files=0)
    with pytest.raises(ValueError, match="max_results"):
        get_change_impact_impl(sandbox, "thing", max_results=0)
    with pytest.raises(ValueError, match="max_tokens"):
        get_change_impact_impl(sandbox, "thing", max_tokens=299)
    with pytest.raises(SandboxError):
        get_change_impact_impl(sandbox, "thing", path="../outside")
