"""Tests for the static project architecture map."""

import pytest

from server.sandbox import Sandbox, SandboxError
from server.tools.project_map_tools import get_project_map_impl


def test_map_finds_python_modules_imports_entrypoints_and_configs(tmp_path):
    root = tmp_path / "demo"
    (root / "pkg").mkdir(parents=True)
    (root / "main.py").write_text(
        'import json\nfrom pkg.service import run\nif __name__ == "__main__":\n    run()\n',
        encoding="utf-8",
    )
    (root / "pkg" / "service.py").write_text(
        "from pathlib import Path\ndef run(): pass\n", encoding="utf-8"
    )
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    result = get_project_map_impl(Sandbox(root))
    assert "main.py" in result
    assert "pkg/service.py" in result
    assert "pkg.service" in result
    assert "ENTRY POINTS" in result
    assert "pyproject.toml" in result


def test_map_skips_generated_and_protected_directories(tmp_path):
    root = tmp_path / "demo"
    (root / ".venv").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "src").mkdir()
    (root / ".venv" / "hidden.py").write_text("secret = True", encoding="utf-8")
    (root / ".git" / "internal.py").write_text("secret = True", encoding="utf-8")
    (root / "src" / "visible.py").write_text("VALUE = 1", encoding="utf-8")

    result = get_project_map_impl(Sandbox(root))
    assert "src/visible.py" in result
    assert "hidden.py" not in result
    assert "internal.py" not in result


def test_map_enforces_file_and_token_limits(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    for index in range(4):
        (root / f"module{index}.py").write_text("import os\n", encoding="utf-8")
    limited = get_project_map_impl(Sandbox(root), max_files=2, max_tokens=600)
    assert "file limit reached" in limited

    for index in range(20):
        filename = f"module{index}_" + ("x" * 90) + ".py"
        (root / filename).write_text("import os\n", encoding="utf-8")
    compact = get_project_map_impl(Sandbox(root), max_files=30, max_tokens=300)
    assert "token budget" in compact


def test_map_rejects_outside_paths_and_invalid_options(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sandbox = Sandbox(root)

    with pytest.raises(SandboxError):
        get_project_map_impl(sandbox, "../outside")
    with pytest.raises(ValueError, match="max_files"):
        get_project_map_impl(sandbox, max_files=0)
    with pytest.raises(ValueError, match="max_tokens"):
        get_project_map_impl(sandbox, max_tokens=299)
