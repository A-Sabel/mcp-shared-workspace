"""Tests for source outline extraction."""

import pytest

from server.sandbox import Sandbox, SandboxError
from server.tools.outline_tools import get_file_outline_impl


def test_python_outline_extracts_imports_classes_and_functions(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "module.py").write_text(
        "import os\nfrom pathlib import Path\n\nclass Worker:\n    def run(self):\n        pass\n\ndef helper():\n    pass\n",
        encoding="utf-8",
    )
    result = get_file_outline_impl(Sandbox(root), "module.py")
    assert "import os" in result
    assert "from pathlib import Path" in result
    assert "class Worker" in result
    assert "def run" in result
    assert "def helper" in result


def test_outline_rejects_non_source_files(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "notes.txt").write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported source type"):
        get_file_outline_impl(Sandbox(root), "notes.txt")


def test_outline_rejects_outside_paths(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("def secret(): pass", encoding="utf-8")
    with pytest.raises(SandboxError):
        get_file_outline_impl(Sandbox(root), "../outside.py")


def test_outline_rejects_invalid_python(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Cannot parse Python source"):
        get_file_outline_impl(Sandbox(root), "bad.py")


def test_outline_limits_symbols(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "many.py").write_text("def a(): pass\ndef b(): pass\n", encoding="utf-8")
    result = get_file_outline_impl(Sandbox(root), "many.py", 1)
    assert "showing 1" in result
    assert "additional symbols omitted" in result
