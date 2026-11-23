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
import re
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from server.config import MAX_GIT_OUTPUT_CHARS
from server.sandbox import Sandbox, SandboxError
from server.tools.schema_utils import set_explicit_required, set_property_type

MAX_COMMIT_MESSAGE_CHARS = 200
MAX_COMMIT_PATHS = 50

MAX_LOG_COMMITS = 20


def git_log_impl(sandbox: Sandbox, limit: int = 10, include_files: bool = True) -> str:
    """Return bounded recent commit history with optional changed-file summaries."""
    if not (sandbox.root / ".git").exists():
        raise SandboxError(
            "Workspace is not a Git repository. Initialize Git before using git_log."
        )
    if not 1 <= limit <= MAX_LOG_COMMITS:
        raise ValueError(f"limit must be between 1 and {MAX_LOG_COMMITS}.")
    args = [
        "log",
        f"--max-count={limit}",
        "--date=short",
        "--pretty=format:%h%x09%ad%x09%s",
    ]
    if include_files:
        args.append("--name-status")
    result = _run_git(sandbox, args)
    if result.returncode != 0:
        detail = _bounded_output(result.stdout, result.stderr)
        raise ValueError(f"git log failed{': ' + detail if detail else '.'}")
    output = result.stdout.strip()
    if not output:
        return "No commits found."
    return _bounded_output(output, "") or "No commits found."


GIT_LOG_DESCRIPTION = (
    "Show recent Git commits with short hash, date, subject, and optionally changed-file "
    "summaries. Results are limited to at most 20 commits and bounded output."
)


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
    mode: str = "unstaged",
) -> str:
    """Return a bounded staged, unstaged, or combined Git diff."""
    if not (sandbox.root / ".git").exists():
        raise SandboxError(
            "Workspace is not a Git repository. "
            "Initialize Git in the workspace before using git_diff."
        )

    if mode not in {"unstaged", "staged", "both"}:
        raise ValueError("mode must be 'unstaged', 'staged', or 'both'.")

    path_args: list[str] = []
    if path is not None:
        safe_path = sandbox.resolve(path)
        path_args = ["--", sandbox.relative(safe_path)]
    else:
        path_args = ["--"]

    diff_args = ["diff", "--no-ext-diff", "--unified=3"]
    if mode == "both":
        sections: list[str] = []
        for section, extra_args in (
            ("staged", ["--cached"]),
            ("unstaged", []),
        ):
            result = _run_git(sandbox, [*diff_args, *extra_args, *path_args])
            if result.returncode != 0:
                detail = _bounded_output(result.stdout, result.stderr)
                raise ValueError(f"git diff failed{': ' + detail if detail else '.'}")
            section_output = result.stdout.strip()
            if section_output:
                sections.append(f"## {section} changes\n{section_output}")
        output = _bounded_output("\n\n".join(sections), "")
        return output or "No both changes."

    extra_args = ["--cached"] if mode == "staged" else []
    result = _run_git(sandbox, [*diff_args, *extra_args, *path_args])
    if result.returncode != 0:
        detail = _bounded_output(result.stdout, result.stderr)
        raise ValueError(f"git diff failed{': ' + detail if detail else '.'}")

    output = _bounded_output(result.stdout, result.stderr)
    return output or f"No {mode} changes."


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
    "Inspect Git changes for the workspace or one safe workspace-relative path. "
    "mode='unstaged' (default) shows working-tree changes, mode='staged' shows "
    "the index, and mode='both' returns separate staged and unstaged sections. Output is bounded."
)

GIT_COMMIT_DESCRIPTION = (
    "Create a Git commit from explicitly supplied workspace-relative paths. "
    "Use git_status and git_diff first to inspect changes. The tool never "
    "stages the entire workspace implicitly, validates paths through the "
    "sandbox, and protects sensitive paths."
)




_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


def _validate_branch_name(name: str) -> str:
    if not isinstance(name, str) or not _BRANCH_RE.fullmatch(name):
        raise ValueError("Branch name contains unsupported characters or is too long.")
    if name.endswith(("/", ".")) or "//" in name or ".." in name or "@{" in name:
        raise ValueError("Branch name is not a safe Git ref.")
    if any(part.startswith(".") or part.endswith(".lock") for part in name.split("/")):
        raise ValueError("Branch name is not a safe Git ref.")
    return name


def git_list_branches_impl(sandbox: Sandbox) -> str:
    if not (sandbox.root / ".git").exists():
        raise SandboxError("Workspace is not a Git repository.")
    result = _run_git(sandbox, ["branch", "--list", "--format=%(HEAD) %(refname:short)"])
    if result.returncode != 0:
        detail = _bounded_output(result.stdout, result.stderr)
        raise ValueError(f"git branch list failed{': ' + detail if detail else '.'}")
    return _bounded_output(result.stdout, result.stderr) or "No local branches found."


def git_create_branch_impl(sandbox: Sandbox, branch_name: str) -> str:
    if not (sandbox.root / ".git").exists():
        raise SandboxError("Workspace is not a Git repository.")
    name = _validate_branch_name(branch_name)
    result = _run_git(sandbox, ["check-ref-format", "--branch", name])
    if result.returncode != 0:
        raise ValueError("Branch name is not a valid Git branch name.")
    exists = _run_git(sandbox, ["show-ref", "--verify", "--quiet", f"refs/heads/{name}"])
    if exists.returncode == 0:
        raise ValueError(f"Branch already exists: {name}.")
    if exists.returncode != 1:
        raise ValueError("Unable to verify whether the branch already exists.")
    created = _run_git(sandbox, ["branch", "--", name])
    if created.returncode != 0:
        detail = _bounded_output(created.stdout, created.stderr)
        raise ValueError(f"git branch creation failed{': ' + detail if detail else '.'}")
    return f"Created local branch {name!r}; the current branch was not changed."


def git_switch_branch_impl(sandbox: Sandbox, branch_name: str) -> str:
    if not (sandbox.root / ".git").exists():
        raise SandboxError("Workspace is not a Git repository.")
    name = _validate_branch_name(branch_name)
    check = _run_git(sandbox, ["check-ref-format", "--branch", name])
    if check.returncode != 0:
        raise ValueError("Branch name is not a valid Git branch name.")
    status = _run_git(sandbox, ["status", "--porcelain", "--untracked-files=all"])
    if status.returncode != 0:
        detail = _bounded_output(status.stdout, status.stderr)
        raise ValueError(f"Unable to inspect working tree{': ' + detail if detail else '.'}")
    if status.stdout.strip():
        raise ValueError("Refusing to switch branches while the working tree has staged, unstaged, or untracked changes. Commit or preserve them first.")
    exists = _run_git(sandbox, ["show-ref", "--verify", "--quiet", f"refs/heads/{name}"])
    if exists.returncode != 0:
        raise ValueError(f"Local branch does not exist: {name}. Create it first with git_create_branch.")
    switched = _run_git(sandbox, ["switch", "--no-guess", "--", name])
    if switched.returncode != 0:
        detail = _bounded_output(switched.stdout, switched.stderr)
        raise ValueError(f"git switch failed{': ' + detail if detail else '.'}")
    return f"Switched to branch {name!r}."


def register(
    mcp: MCPServer,
    sandbox: Sandbox,
    client_id: str = "workspace-client",
    log_path: Path | None = None,
) -> None:
    """Register Git tools allowed for the supplied role."""
    if log_path is None:
        log_path = sandbox.root / ".tool_calls.jsonl"

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
                    "Optional workspace-relative file or directory to diff. "
                    "Omit to inspect the whole workspace."
                ),
            ),
        ] = None,
        mode: Annotated[
            str,
            Field(description="Diff view: unstaged (default), staged, or both."),
        ] = "unstaged",
    ) -> str:
        """Show bounded staged, unstaged, or combined Git changes."""
        return git_diff_impl(sandbox, path, mode)

    mcp.add_tool(
        git_diff,
        name="git_diff",
        description=GIT_DIFF_DESCRIPTION,
        structured_output=False,
    )
    set_explicit_required(mcp, "git_diff")
    set_property_type(mcp, "git_diff", "path", "string")
    set_property_type(mcp, "git_diff", "mode", "string")

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
        return git_commit_impl(sandbox, message, paths)

    mcp.add_tool(
        git_commit,
        name="git_commit",
        description=GIT_COMMIT_DESCRIPTION,
        structured_output=False,
    )

    @audited(
        tool_name="git_log",
        role=client_id,
        log_path=log_path,
        summarize=lambda _a, kw: {
            "limit": kw.get("limit"),
            "include_files": kw.get("include_files"),
        },
    )
    def git_log(
        limit: Annotated[int, Field(ge=1, le=MAX_LOG_COMMITS, description="Maximum number of recent commits.")] = 10,
        include_files: Annotated[bool, Field(description="Include changed-file names and status codes.")] = True,
    ) -> str:
        """Show recent commits and compact changed-file summaries."""
        return git_log_impl(sandbox, limit, include_files)

    mcp.add_tool(
        git_log,
        name="git_log",
        description=GIT_LOG_DESCRIPTION,
        structured_output=False,
    )

    @audited(tool_name="git_list_branches", role=client_id, log_path=log_path,
             summarize=lambda _a, _kw: {})
    def git_list_branches() -> str:
        """List local branches and mark the current branch."""
        return git_list_branches_impl(sandbox)

    mcp.add_tool(git_list_branches, name="git_list_branches", structured_output=False)

    @audited(tool_name="git_create_branch", role=client_id, log_path=log_path,
             summarize=lambda _a, kw: {"branch_name": kw.get("branch_name")})
    def git_create_branch(
        branch_name: Annotated[str, Field(min_length=1, max_length=128, description="New local branch name.")],
    ) -> str:
        """Create a local branch without switching to it or overwriting an existing branch."""
        return git_create_branch_impl(sandbox, branch_name)

    mcp.add_tool(git_create_branch, name="git_create_branch", structured_output=False)

    @audited(tool_name="git_switch_branch", role=client_id, log_path=log_path,
             summarize=lambda _a, kw: {"branch_name": kw.get("branch_name")})
    def git_switch_branch(
        branch_name: Annotated[str, Field(min_length=1, max_length=128, description="Existing local branch name.")],
    ) -> str:
        """Switch branches only when the working tree is completely clean."""
        return git_switch_branch_impl(sandbox, branch_name)

    mcp.add_tool(git_switch_branch, name="git_switch_branch", structured_output=False)
