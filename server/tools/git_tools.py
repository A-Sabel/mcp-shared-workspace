"""Git tools for the MCP shared workspace."""

from __future__ import annotations

from pathlib import Path

from server.audit_summaries import (
    git_commit_summary,
    git_diff_summary,
    git_status_summary,
)
from server.audited_tool import audited

import subprocess
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from server.config import MAX_GIT_OUTPUT_CHARS
from server.sandbox import Sandbox, SandboxError

MAX_COMMIT_MESSAGE_CHARS = 200
MAX_COMMIT_PATHS = 50


def _run_git(
    sandbox: Sandbox,
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    """Run a bounded Git command in the workspace."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=sandbox.root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
        )
    except OSError as exc:
        raise ValueError(f"Unable to run Git: {exc}.") from None


def _bounded_output(
    stdout: str,
    stderr: str,
) -> str:
    """Return compact bounded command output."""
    output = stdout.strip()

    if stderr.strip():
        if output:
            output += f"\n[git stderr]\n{stderr.strip()}"
        else:
            output = stderr.strip()

    if len(output) > MAX_GIT_OUTPUT_CHARS:
        output = output[:MAX_GIT_OUTPUT_CHARS].rstrip() + "\n[output truncated]"

    return output


def git_status_impl(sandbox: Sandbox) -> str:
    """Return concise Git status for the workspace."""
    if not (sandbox.root / ".git").exists():
        raise SandboxError(
            "Workspace is not a Git repository. "
            "Initialize Git in the workspace before using git_status."
        )

    result = _run_git(
        sandbox,
        [
            "status",
            "--short",
            "--branch",
        ],
    )

    if result.returncode != 0:
        detail = _bounded_output(
            result.stdout,
            result.stderr,
        )
        raise ValueError(f"git status failed" f"{f': {detail}' if detail else '.'}")

    output = _bounded_output(
        result.stdout,
        result.stderr,
    )

    return output or "Working tree clean."


def git_diff_impl(
    sandbox: Sandbox,
    path: str | None = None,
) -> str:
    """Return a bounded Git diff for the workspace."""
    if not (sandbox.root / ".git").exists():
        raise SandboxError(
            "Workspace is not a Git repository. "
            "Initialize Git in the workspace before using git_diff."
        )

    args = [
        "diff",
        "--no-ext-diff",
        "--unified=3",
    ]

    if path is not None:
        # Validate the requested path through the sandbox before giving it
        # to Git. Git receives it as a separate argument, never through a shell.
        safe_path = sandbox.resolve(path)
        relative_path = sandbox.relative(safe_path)
        args.extend(["--", relative_path])
    else:
        args.append("--")

    result = _run_git(sandbox, args)

    if result.returncode != 0:
        detail = _bounded_output(
            result.stdout,
            result.stderr,
        )
        raise ValueError(f"git diff failed" f"{f': {detail}' if detail else '.'}")

    output = _bounded_output(
        result.stdout,
        result.stderr,
    )

    return output or "No unstaged changes."


def git_commit_impl(
    sandbox: Sandbox,
    message: str,
    paths: list[str],
) -> str:
    """Stage explicit safe paths and create a Git commit."""
    if not (sandbox.root / ".git").exists():
        raise SandboxError(
            "Workspace is not a Git repository. "
            "Initialize Git in the workspace before using git_commit."
        )

    if not isinstance(message, str) or not message.strip():
        raise ValueError("Commit message must not be empty.")

    message = message.strip()

    if len(message) > MAX_COMMIT_MESSAGE_CHARS:
        raise ValueError(
            f"Commit message exceeds the "
            f"{MAX_COMMIT_MESSAGE_CHARS}-character limit."
        )

    if not isinstance(paths, list) or not paths:
        raise ValueError(
            "At least one path must be provided. "
            "git_commit never stages the entire workspace implicitly."
        )

    if len(paths) > MAX_COMMIT_PATHS:
        raise ValueError(f"At most {MAX_COMMIT_PATHS} paths may be committed at once.")

    safe_paths: list[str] = []

    for index, path in enumerate(paths, start=1):
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"Path {index} must be a non-empty string.")

        try:
            resolved = sandbox.resolve(path, for_write=True)
        except SandboxError as exc:
            raise ValueError(f"Path {index} {path!r} is not allowed: {exc}") from None

        if resolved == sandbox.root:
            raise ValueError("The workspace root itself cannot be committed as a path.")

        relative = sandbox.relative(resolved)

        if relative not in safe_paths:
            safe_paths.append(relative)

    if not safe_paths:
        raise ValueError("No valid paths were provided.")

    # Stage only the explicitly approved paths.
    add_result = _run_git(
        sandbox,
        [
            "add",
            "--",
            *safe_paths,
        ],
    )

    if add_result.returncode != 0:
        detail = _bounded_output(
            add_result.stdout,
            add_result.stderr,
        )
        raise ValueError(f"git add failed" f"{f': {detail}' if detail else '.'}")

    commit_result = _run_git(
        sandbox,
        [
            "commit",
            "-m",
            message,
            "--",
            *safe_paths,
        ],
    )

    if commit_result.returncode != 0:
        detail = _bounded_output(
            commit_result.stdout,
            commit_result.stderr,
        )
        raise ValueError(f"git commit failed" f"{f': {detail}' if detail else '.'}")

    output = _bounded_output(
        commit_result.stdout,
        commit_result.stderr,
    )

    return output or "Commit created successfully."


GIT_STATUS_DESCRIPTION = (
    "Show the current Git branch and concise working-tree changes for the "
    "workspace. Use before editing or committing to understand the current "
    "repository state. Output is bounded."
)

GIT_DIFF_DESCRIPTION = (
    "Show the current unstaged Git diff for the workspace or one safe "
    "workspace-relative path. Use after editing to inspect what changed "
    "before committing. Output is bounded."
)

GIT_COMMIT_DESCRIPTION = (
    "Create a Git commit from explicitly supplied workspace-relative paths. "
    "Use git_status and git_diff first to inspect changes. The tool never "
    "stages the entire workspace implicitly, validates paths through the "
    "sandbox, and protects sensitive paths."
)


def register(
    mcp: MCPServer,
    sandbox: Sandbox,
    client_id: str = "workspace-client",
    log_path: Path | None = None,
) -> None:
    """Register Git tools allowed for the supplied role."""
    if log_path is None:
        log_path = sandbox.root / ".tool_calls.jsonl"

    if True:

        @audited(
            tool_name="git_status",
            role=client_id,
            log_path=log_path,
            summarize=git_status_summary,
        )
        def git_status() -> str:
            """Show concise Git status for the workspace."""
            return git_status_impl(sandbox)

        mcp.add_tool(
            git_status,
            name="git_status",
            description=GIT_STATUS_DESCRIPTION,
            structured_output=False,
        )

    if True:

        @audited(
            tool_name="git_diff",
            role=client_id,
            log_path=log_path,
            summarize=git_diff_summary,
        )
        def git_diff(
            path: Annotated[
                str | None,
                Field(
                    description=(
                        "Optional workspace-relative file or directory to "
                        "diff. Omit to inspect all unstaged changes."
                    ),
                ),
            ] = None,
        ) -> str:
            """Show bounded unstaged Git changes."""
            return git_diff_impl(sandbox, path)

        mcp.add_tool(
            git_diff,
            name="git_diff",
            description=GIT_DIFF_DESCRIPTION,
            structured_output=False,
        )

    if True:

        @audited(
            tool_name="git_commit",
            role=client_id,
            log_path=log_path,
            summarize=git_commit_summary,
        )
        def git_commit(
            message: Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=MAX_COMMIT_MESSAGE_CHARS,
                    description="Short Git commit message.",
                ),
            ],
            paths: Annotated[
                list[str],
                Field(
                    min_length=1,
                    max_length=MAX_COMMIT_PATHS,
                    description=(
                        "Explicit workspace-relative files to stage and commit. "
                        "The entire workspace is never committed implicitly."
                    ),
                ),
            ],
        ) -> str:
            """Create a commit from explicitly selected safe paths."""
            return git_commit_impl(
                sandbox,
                message,
                paths,
            )

        mcp.add_tool(
            git_commit,
            name="git_commit",
            description=GIT_COMMIT_DESCRIPTION,
            structured_output=False,
        )
