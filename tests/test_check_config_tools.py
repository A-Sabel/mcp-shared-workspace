"""Tests for configurable, allowlisted project checks."""

import json
import subprocess

import pytest

from server.sandbox import Sandbox
from server.tools import check_tools


def test_project_config_selects_paths_but_not_commands(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "unit").mkdir()
    (tmp_path / ".mcp-workspace-checks.json").write_text(
        json.dumps({"pytest": {"paths": ["tests/unit"]}}), encoding="utf-8"
    )
    calls = []
    monkeypatch.setattr(check_tools, "_module_available", lambda _module: True)

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr(check_tools.subprocess, "run", fake_run)
    result = check_tools.run_project_checks_impl(Sandbox(tmp_path), ["pytest"])
    assert "PASSED" in result
    assert calls == [[check_tools.sys.executable, "-m", "pytest", "-q", "tests/unit"]]


@pytest.mark.parametrize("config", [
    {"pytest": {"command": "echo unsafe"}},
    {"unknown": {"paths": ["tests"]}},
    {"pytest": {"paths": ["../outside"]}},
    {"pytest": {"paths": ["--collect-only"]}},
    {"pytest": {"paths": ["missing"]}},
])
def test_project_config_rejects_unsafe_or_unknown_options(tmp_path, config):
    (tmp_path / "tests").mkdir()
    (tmp_path / ".mcp-workspace-checks.json").write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError):
        check_tools.run_project_checks_impl(Sandbox(tmp_path), ["pytest"])


def test_project_config_rejects_symlink(tmp_path):
    (tmp_path / "tests").mkdir()
    outside = tmp_path.parent / "outside-check-config.json"
    outside.write_text("{}", encoding="utf-8")
    try:
        (tmp_path / ".mcp-workspace-checks.json").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    with pytest.raises(ValueError, match="regular file"):
        check_tools.run_project_checks_impl(Sandbox(tmp_path), ["pytest"])
