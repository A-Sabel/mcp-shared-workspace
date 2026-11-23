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


def _explicit_git_paths(sandbox: Sandbox, paths: list[str]) -> list[str]:
    if not isinstance(paths, list) or not paths:
        raise ValueError("Provide at least one explicit path; workspace-wide operations are not allowed.")
    if len(paths) > 50:
        raise ValueError("At most 50 paths may be supplied.")
    safe: list[str] = []
    for path in paths:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("Every path must be a non-empty workspace-relative string.")
        resolved = sandbox.resolve(path, for_write=True)
        if resolved == sandbox.root:
            raise ValueError("The workspace root cannot be selected.")
        relative = sandbox.relative(resolved)
        if relative not in safe:
            safe.append(relative)
    return safe


def git_unstage_impl(sandbox: Sandbox, paths: list[str]) -> str:
    safe = _explicit_git_paths(sandbox, paths)
    result = _run_git(sandbox, ["reset", "--quiet", "HEAD", "--", *safe])
    if result.returncode != 0:
        detail = _bounded_output(result.stdout, result.stderr)
        raise ValueError(f"git unstage failed{': ' + detail if detail else '.'}")
    return "Unstaged only: " + ", ".join(safe) + ". Working-tree files were not changed."


def git_restore_impl(sandbox: Sandbox, paths: list[str], confirm: bool = False, dry_run: bool = True) -> str:
    safe = _explicit_git_paths(sandbox, paths)
    if dry_run:
        status = _run_git(sandbox, ["status", "--short", "--", *safe])
        if status.returncode != 0:
            raise ValueError("Unable to preview selected restore paths.")
        return "DRY RUN — would discard unstaged working-tree changes for: " + ", ".join(safe) + ".\n" + (status.stdout.strip() or "No matching working-tree changes.")
    if confirm is not True:
        raise ValueError("Destructive restore requires confirm=true. Run dry_run=true first.")
    result = _run_git(sandbox, ["restore", "--worktree", "--", *safe])
    if result.returncode != 0:
        detail = _bounded_output(result.stdout, result.stderr)
        raise ValueError(f"git restore failed{': ' + detail if detail else '.'}")
    return "Restored working-tree content for explicit paths only: " + ", ".join(safe)


_STASH_REF_RE = re.compile(r"^stash@\\{[0-9]{1,6}\\}$")


def _validate_stash_ref(ref: str) -> str:
    if (not isinstance(ref, str) or not ref.startswith("stash@{") or not ref.endswith("}")
            or not ref[7:-1].isdigit() or len(ref[7:-1]) > 6):
        raise ValueError("Use a stash reference in the form stash@{0}.")
    return ref


def _require_clean_worktree_for_stash_apply(sandbox: Sandbox) -> None:
    """Refuse stash application while local changes could be overwritten."""
    status = _run_git(sandbox, ["status", "--porcelain", "--untracked-files=all"])
    if status.returncode != 0:
        raise ValueError("Unable to check working-tree state before applying stash.")
    if status.stdout.strip():
        raise ValueError(
            "Cannot apply or pop a stash while the working tree has staged, "
            "unstaged, or untracked changes. Commit or stash those changes first."
        )


def git_stash_impl(sandbox: Sandbox, action: str, include_untracked: bool = False,
                   message: str = "MCP workspace stash", stash_ref: str = "stash@{0}",
                   confirm: bool = False) -> str:
    if action == "list":
        result = _run_git(sandbox, ["stash", "list", "--format=%gd %gs"])
    elif action == "push":
        args = ["stash", "push"]
        if include_untracked:
            args.append("--include-untracked")
        args.extend(["-m", message])
        result = _run_git(sandbox, args)
    elif action in {"apply", "pop", "drop"}:
        ref = _validate_stash_ref(stash_ref)
        if action == "drop":
            if confirm is not True:
                raise ValueError("Dropping a stash is destructive; require confirm=true.")
            result = _run_git(sandbox, ["stash", "drop", ref])
        elif action == "apply":
            _require_clean_worktree_for_stash_apply(sandbox)
            result = _run_git(sandbox, ["stash", "apply", ref])
        else:
            # Apply first; retain the stash whenever applying fails or conflicts.
            _require_clean_worktree_for_stash_apply(sandbox)
            applied = _run_git(sandbox, ["stash", "apply", ref])
            if applied.returncode != 0:
                detail = _bounded_output(applied.stdout, applied.stderr)
                raise ValueError(f"Stash apply failed; stash retained: {detail}")
            result = _run_git(sandbox, ["stash", "drop", ref])
            if result.returncode != 0:
                detail = _bounded_output(result.stdout, result.stderr)
                raise ValueError(f"Stash applied, but could not drop it: {detail}")
            return _bounded_output(applied.stdout, applied.stderr) or f"Applied and dropped {ref}."
    else:
        raise ValueError("action must be list, push, apply, pop, or drop.")
    if result.returncode != 0:
        detail = _bounded_output(result.stdout, result.stderr)
        raise ValueError(f"git stash {action} failed{': ' + detail if detail else '.'}")
    return _bounded_output(result.stdout, result.stderr) or f"git stash {action} completed."


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

    @audited(tool_name="git_unstage", role=client_id, log_path=log_path,
             summarize=lambda _a, kw: {"paths": kw.get("paths", [])})
    def git_unstage(paths: Annotated[list[str], Field(min_length=1, max_length=50,
                       description="Explicit workspace-relative paths to unstage; working files remain unchanged.")]) -> str:
        """Remove selected paths from the index without changing working-tree files."""
        return git_unstage_impl(sandbox, paths)
    mcp.add_tool(git_unstage, name="git_unstage", structured_output=False)

    @audited(tool_name="git_restore", role=client_id, log_path=log_path,
             summarize=lambda _a, kw: {"paths": kw.get("paths", []), "dry_run": kw.get("dry_run")})
    def git_restore(
        paths: Annotated[list[str], Field(min_length=1, max_length=50,
               description="Explicit workspace-relative paths only; no workspace-wide restore.")],
        confirm: Annotated[bool, Field(description="Must be true for destructive execution.")] = False,
        dry_run: Annotated[bool, Field(description="Preview only; defaults to true.")] = True,
    ) -> str:
        """Preview or restore only explicit working-tree paths; destructive execution requires confirmation."""
        return git_restore_impl(sandbox, paths, confirm, dry_run)
    mcp.add_tool(git_restore, name="git_restore", structured_output=False)

    @audited(tool_name="git_stash", role=client_id, log_path=log_path,
             summarize=lambda _a, kw: {"action": kw.get("action"), "include_untracked": kw.get("include_untracked")})
    def git_stash(
        action: Annotated[str, Field(description="list, push, apply, pop, or drop.")],
        include_untracked: Annotated[bool, Field(description="Explicitly include untracked files on push.")] = False,
        message: Annotated[str, Field(max_length=200, description="Stash message for push.")] = "MCP workspace stash",
        stash_ref: Annotated[str, Field(description="Explicit stash reference, e.g. stash@{0}.")] = "stash@{0}",
        confirm: Annotated[bool, Field(description="Must be true to drop a stash.")] = False,
    ) -> str:
        """Manage stashes; pop applies before dropping, and retains the stash if apply conflicts."""
        return git_stash_impl(sandbox, action, include_untracked, message, stash_ref, confirm)
    mcp.add_tool(git_stash, name="git_stash", structured_output=False)

