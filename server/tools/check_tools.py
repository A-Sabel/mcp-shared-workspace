"""Run explicitly allowlisted, project-configured quality checks."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from server.audited_tool import audited
from server.sandbox import Sandbox

CheckName = Literal["pytest", "ruff", "mypy"]
DEFAULT_TIMEOUT_SECONDS = 120
MAX_TIMEOUT_SECONDS = 300
DEFAULT_OUTPUT_CHARS = 6000
MAX_OUTPUT_CHARS = 20000

CHECK_CONFIGS: dict[str, tuple[str, ...]] = {
    "pytest": ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"),
    "ruff": ("ruff.toml", ".ruff.toml", "pyproject.toml"),
    "mypy": ("mypy.ini", ".mypy.ini", "pyproject.toml", "setup.cfg"),
}


def _has_check_config(root: Path, check: str) -> bool:
    if check == "pytest":
        return (root / "tests").is_dir() or any(
            (root / name).is_file() for name in CHECK_CONFIGS[check]
        )
    return any((root / name).is_file() for name in CHECK_CONFIGS[check])


def _module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _command_for(check: str) -> list[str]:
    if check == "pytest":
        return [sys.executable, "-m", "pytest", "-q"]
    if check == "ruff":
        return [sys.executable, "-m", "ruff", "check", "."]
    if check == "mypy":
        return [sys.executable, "-m", "mypy", "."]
    raise ValueError(f"Unsupported check: {check}")


def _clip_output(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    marker = "\n[output truncated]"
    return value[: max(0, limit - len(marker))].rstrip() + marker


def run_project_checks_impl(
    sandbox: Sandbox,
    checks: Sequence[str] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_output_chars: int = DEFAULT_OUTPUT_CHARS,
) -> str:
    """Run only supported checks with matching project configuration."""
    selected = ["pytest"] if checks is None else checks
    if not selected:
        raise ValueError("Select at least one check.")
    unknown = sorted(set(selected) - set(CHECK_CONFIGS))
    if unknown:
        raise ValueError(f"Unsupported check(s): {', '.join(unknown)}.")
    if len(selected) != len(set(selected)):
        raise ValueError("Duplicate checks are not allowed.")
    if not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError(f"timeout_seconds must be between 1 and {MAX_TIMEOUT_SECONDS}.")
    if not 500 <= max_output_chars <= MAX_OUTPUT_CHARS:
        raise ValueError(f"max_output_chars must be between 500 and {MAX_OUTPUT_CHARS}.")

    results: list[str] = []
    for check in selected:
        if not _has_check_config(sandbox.root, check):
            results.append(f"## {check}\nSKIPPED: no recognized project configuration or tests directory.")
            continue
        if not _module_available(check):
            results.append(f"## {check}\nSKIPPED: {check} is not installed in the server Python environment.")
            continue

        command = _command_for(check)
        try:
            completed = subprocess.run(
                command,
                cwd=sandbox.root,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            output = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
            results.append(
                f"## {check}\nTIMEOUT after {timeout_seconds}s\n"
                f"{_clip_output(output, max_output_chars) or '(no output)'}"
            )
            continue
        except OSError as exc:
            results.append(f"## {check}\nERROR: unable to start check: {exc}")
            continue

        output = "\n".join(
            part for part in (completed.stdout.strip(), completed.stderr.strip()) if part
        )
        status = "PASSED" if completed.returncode == 0 else f"FAILED (exit code {completed.returncode})"
        results.append(
            f"## {check}\n{status}\n"
            f"{_clip_output(output, max_output_chars) or '(no output)'}"
        )

    return "\n\n".join(results)


def register(
    mcp: MCPServer,
    sandbox: Sandbox,
    client_id: str = "workspace-client",
    log_path: Path | None = None,
) -> None:
    if log_path is None:
        log_path = sandbox.root / ".tool_calls.jsonl"

    @audited(
        tool_name="run_project_checks",
        role=client_id,
        log_path=log_path,
        summarize=lambda _a, kw: {
            "checks": kw.get("checks"),
            "timeout_seconds": kw.get("timeout_seconds"),
        },
    )
    def run_project_checks(
        checks: Annotated[
            list[CheckName],
            Field(description="Allowlisted checks to run: pytest, ruff, and/or mypy. Defaults to pytest."),
        ] = ["pytest"],
        timeout_seconds: Annotated[
            int,
            Field(ge=1, le=MAX_TIMEOUT_SECONDS, description="Per-check timeout in seconds; maximum 300."),
        ] = DEFAULT_TIMEOUT_SECONDS,
        max_output_chars: Annotated[
            int,
            Field(ge=500, le=MAX_OUTPUT_CHARS, description="Maximum returned output characters per check."),
        ] = DEFAULT_OUTPUT_CHARS,
    ) -> str:
        """Run explicitly configured pytest, Ruff, or mypy checks; arbitrary commands are not accepted."""
        return run_project_checks_impl(sandbox, checks, timeout_seconds, max_output_chars)

    mcp.add_tool(run_project_checks, name="run_project_checks", structured_output=False)
