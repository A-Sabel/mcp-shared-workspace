"""High-level, bounded project context for coding agents."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from server.audited_tool import audited
from server.sandbox import Sandbox, SandboxError
from server.tools.git_tools import git_status_impl, _run_git

ContextSection = Literal[
    "project_structure",
    "git_status",
    "project_instructions",
    "project_state",
    "recent_changes",
]
DEFAULT_SECTIONS = ("project_structure", "git_status", "project_instructions", "project_state", "recent_changes")
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build"}
INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md")
STATE_FILES = ("PROJECT_STATE.md", "PLAN_LOG.md", "CHECKPOINTS.md", "DECISIONS.md")
MAX_CONTEXT_TOKENS = 6000


def _clip(text: str, chars: int) -> str:
    if len(text) <= chars:
        return text
    return text[: max(0, chars - 24)].rstrip() + "\n[section truncated]"


def _structure(sandbox: Sandbox, max_entries: int = 80) -> str:
    entries: list[str] = []
    for current, dirs, files in os.walk(sandbox.root):
        current_path = Path(current)
        dirs[:] = sorted(
            d for d in dirs
            if d not in SKIP_DIRS and not sandbox.is_protected(current_path / d)
        )
        depth = len(current_path.relative_to(sandbox.root).parts)
        if depth > 5:
            dirs[:] = []
            continue
        for name in sorted(files):
            path = current_path / name
            if sandbox.is_protected(path):
                continue
            entries.append(sandbox.relative(path))
            if len(entries) >= max_entries:
                return "\n".join(entries) + f"\n[structure capped at {max_entries} files]"
    return "\n".join(entries) if entries else "(no visible files)"


def _read_known_files(sandbox: Sandbox, names: tuple[str, ...], per_file_chars: int) -> str:
    blocks: list[str] = []
    for name in names:
        try:
            path = sandbox.resolve(name)
        except SandboxError:
            continue
        if not path.is_file() or path.stat().st_size > 128_000:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if content.strip():
            blocks.append(f"### {name}\n{_clip(content, per_file_chars)}")
    return "\n\n".join(blocks) if blocks else "(none found)"


def get_workspace_context_impl(
    sandbox: Sandbox,
    sections: list[str] | tuple[str, ...] = DEFAULT_SECTIONS,
    max_tokens: int = 2000,
) -> str:
    if not 300 <= max_tokens <= MAX_CONTEXT_TOKENS:
        raise ValueError(f"max_tokens must be between 300 and {MAX_CONTEXT_TOKENS}.")
    allowed = set(DEFAULT_SECTIONS)
    unknown = set(sections) - allowed
    if unknown:
        raise ValueError(f"Unknown context section(s): {', '.join(sorted(unknown))}.")
    if not sections:
        raise ValueError("At least one context section must be selected.")

    budget = max_tokens * 4
    per_section = max(300, budget // len(sections))
    blocks = [f"WORKSPACE: {sandbox.root.name}", f"CONTEXT BUDGET: approximately {max_tokens} tokens"]
    for section in sections:
        if section == "project_structure":
            content = _structure(sandbox)
        elif section == "git_status":
            try:
                content = git_status_impl(sandbox)
            except (SandboxError, ValueError) as exc:
                content = f"(unavailable: {exc})"
        elif section == "project_instructions":
            content = _read_known_files(sandbox, INSTRUCTION_FILES, min(per_section, 6000))
        elif section == "project_state":
            content = _read_known_files(sandbox, STATE_FILES, min(per_section, 5000))
        else:
            result = _run_git(sandbox, ["diff", "--stat", "HEAD", "--"])
            if result.returncode == 0:
                content = result.stdout.strip() or "(no tracked changes since HEAD)"
                untracked = _run_git(sandbox, ["ls-files", "--others", "--exclude-standard"])
                if untracked.returncode == 0 and untracked.stdout.strip():
                    content += "\nUntracked files:\n" + untracked.stdout.strip()
            else:
                content = "(unavailable: workspace is not a Git repository)"
        blocks.append(f"## {section.replace('_', ' ').title()}\n{_clip(content, per_section)}")
    return _clip("\n\n".join(blocks), budget)


def register(mcp: MCPServer, sandbox: Sandbox, client_id: str = "workspace-client", log_path: Path | None = None) -> None:
    if log_path is None:
        log_path = sandbox.root / ".tool_calls.jsonl"

    @audited(tool_name="get_workspace_context", role=client_id, log_path=log_path,
             summarize=lambda _a, kw: {"sections": kw.get("sections"), "max_tokens": kw.get("max_tokens")})
    def get_workspace_context(
        sections: Annotated[list[ContextSection], Field(description="Context sections to include. Defaults to all available sections.")] = list(DEFAULT_SECTIONS),
        max_tokens: Annotated[int, Field(ge=300, le=MAX_CONTEXT_TOKENS, description="Approximate output budget in tokens.")] = 2000,
    ) -> str:
        """Return compact project structure, Git status, instructions, shared state, and recent changes."""
        return get_workspace_context_impl(sandbox, sections, max_tokens)

    mcp.add_tool(get_workspace_context, name="get_workspace_context", structured_output=False)
