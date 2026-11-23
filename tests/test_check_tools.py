"""Tests for the allowlisted project-check runner."""

import subprocess

import pytest

from server.sandbox import Sandbox
from server.tools import check_tools


def test_runner_uses_fixed_pytest_command_and_returns_result(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    calls = []
    monkeypatch.setattr(check_tools, "_module_available", lambda _module: True)

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "3 passed", "")

    monkeypatch.setattr(check_tools.subprocess, "run", fake_run)
    result = check_tools.run_project_checks_impl(Sandbox(tmp_path))

    assert "PASSED" in result
    assert "3 passed" in result
    assert calls[0][0] == [check_tools.sys.executable, "-m", "pytest", "-q"]
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["timeout"] == check_tools.DEFAULT_TIMEOUT_SECONDS


def test_runner_skips_unconfigured_and_missing_checks(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    monkeypatch.setattr(check_tools, "_module_available", lambda _module: False)
    result = check_tools.run_project_checks_impl(Sandbox(tmp_path), ["pytest", "ruff"])
    assert "pytest" in result and "not installed" in result
    assert "ruff" in result and "SKIPPED" in result
    assert "no recognized project configuration" in result


def test_runner_rejects_arbitrary_commands(tmp_path):
    with pytest.raises(ValueError, match="Unsupported check"):
        check_tools.run_project_checks_impl(Sandbox(tmp_path), ["python -c print(1)"])


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"timeout_seconds": 301}, "timeout_seconds"),
        ({"max_output_chars": 100}, "max_output_chars"),
        ({"checks": []}, "at least one"),
    ],
)
def test_runner_validates_limits_and_selection(tmp_path, kwargs, message):
    with pytest.raises(ValueError, match=message):
        check_tools.run_project_checks_impl(Sandbox(tmp_path), **kwargs)


def test_runner_bounds_output(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    monkeypatch.setattr(check_tools, "_module_available", lambda _module: True)
    monkeypatch.setattr(
        check_tools.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "x" * 2000, ""),
    )
    result = check_tools.run_project_checks_impl(Sandbox(tmp_path), ["pytest"], max_output_chars=500)
    assert "[output truncated]" in result
    assert len(result.split("\n", 2)[-1]) <= 500


def test_runner_reports_timeout(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    monkeypatch.setattr(check_tools, "_module_available", lambda _module: True)

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="still running")

    monkeypatch.setattr(check_tools.subprocess, "run", timeout)
    result = check_tools.run_project_checks_impl(Sandbox(tmp_path), timeout_seconds=2)
    assert "TIMEOUT after 2s" in result
    assert "still running" in result
