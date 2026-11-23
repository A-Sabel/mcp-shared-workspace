"""Static, bounded architecture mapping for coding agents."""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from server.audited_tool import audited
from server.sandbox import Sandbox

SKIP_DIRS = {
    ".git", ".trash", ".venv", "venv", "env", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", "dist", "build", "coverage", ".next", ".turbo",
}
SOURCE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".java", ".php", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs",
}
CONFIG_FILES = {
    "pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg", "setup.py",
    "requirements.txt", "package.json", "package-lock.json", "pnpm-lock.yaml",
    "yarn.lock", "tsconfig.json", "jsconfig.json", "vite.config.js",
    "vite.config.ts", "webpack.config.js", "Cargo.toml", "go.mod",
    "pom.xml", "build.gradle", "build.gradle.kts", "composer.json",
    "Dockerfile", "docker-compose.yml", "compose.yml", "Makefile",
    ".mcp.json", "mcp.json", "ruff.toml", ".ruff.toml", "mypy.ini",
    ".mypy.ini", ".gitignore", ".env.example",
}
MAX_FILES = 300
MAX_MAP_TOKENS = 6000
IMPORT_RE = re.compile(
    r"""^\s*(?:import\s+([\w./-]+)|from\s+([\w./-]+)\s+import|"""
    r"""#include\s*[<"]([^>"]+)[>"]|require\(["']([^"']+)["']\)|"""
    r"""(?:const|let|var)\s+.*?\s+from\s+["']([^"']+)["'])""",
)
ENTRY_NAMES = {
    "__main__.py", "main.py", "app.py", "wsgi.py", "asgi.py",
    "manage.py", "cli.py", "index.js", "index.ts", "server.js",
    "server.ts", "main.go", "main.rs",
}


def _walk_sources(sandbox: Sandbox, start: Path, max_files: int) -> tuple[list[Path], bool]:
    found: list[Path] = []
    truncated = False
    for current, dirs, files in os.walk(start, followlinks=False):
        current_path = Path(current)
        dirs[:] = sorted(
            name for name in dirs
            if name not in SKIP_DIRS
            and not sandbox.is_protected(current_path / name)
            and not (current_path / name).is_symlink()
        )
        for name in sorted(files):
            path = current_path / name
            if sandbox.is_protected(path) or path.is_symlink():
                continue
            if path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            found.append(path)
            if len(found) > max_files:
                truncated = True
                return found[:max_files], truncated
    return found, truncated


def _python_imports(path: Path, root: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append("." * node.level + node.module)
            elif node.level:
                imports.append("." * node.level)
    return sorted(set(imports))


def _imports(path: Path, root: Path) -> list[str]:
    if path.suffix.lower() == ".py":
        return _python_imports(path, root)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    values: set[str] = set()
    for line in lines:
        match = IMPORT_RE.match(line)
        if match:
            values.add(next(group for group in match.groups() if group))
    return sorted(values)


def _module_name(path: Path, root: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return relative


def _entry_points(root: Path, files: list[Path]) -> list[str]:
    entries: set[str] = set()
    for path in files:
        if path.name in ENTRY_NAMES:
            entries.add(path.relative_to(root).as_posix())
        if path.suffix.lower() == ".py":
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if '__name__ == "__main__"' in source or "__name__ == '__main__'" in source:
                entries.add(path.relative_to(root).as_posix())
    package = root / "package.json"
    if package.is_file() and not package.is_symlink():
        try:
            import json
            data = json.loads(package.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {})
            for name in ("start", "dev", "serve"):
                if isinstance(scripts, dict) and name in scripts:
                    entries.add(f"package.json scripts.{name}: {scripts[name]}")
        except (OSError, UnicodeDecodeError, ValueError):
            pass
    return sorted(entries)


def get_project_map_impl(
    sandbox: Sandbox,
    path: str = ".",
    max_files: int = 150,
    max_tokens: int = 2500,
) -> str:
    """Build a static module/dependency/entry-point/configuration overview."""
    if not 1 <= max_files <= MAX_FILES:
        raise ValueError(f"max_files must be between 1 and {MAX_FILES}.")
    if not 300 <= max_tokens <= MAX_MAP_TOKENS:
        raise ValueError(f"max_tokens must be between 300 and {MAX_MAP_TOKENS}.")

    start = sandbox.resolve(path)
    if not start.is_dir():
        raise ValueError(f"Path {path!r} is not a directory.")

    files, truncated = _walk_sources(sandbox, start, max_files)
    root_configs = [
        item.name for item in sorted(start.iterdir(), key=lambda p: p.name.lower())
        if item.is_file() and not item.is_symlink() and item.name in CONFIG_FILES
        and not sandbox.is_protected(item)
    ]
    modules: list[str] = []
    dependency_count = 0
    for item in files:
        rel = _module_name(item, start)
        deps = _imports(item, start)
        dependency_count += len(deps)
        shown_deps = ", ".join(deps[:8]) if deps else "(no imports detected)"
        if len(deps) > 8:
            shown_deps += f", +{len(deps) - 8} more"
        modules.append(f"- {rel} -> {shown_deps}")

    entries = _entry_points(start, files)
    sections = [
        f"PROJECT MAP: {start.name or '.'}",
        f"SCOPE: {path} | source files: {len(files)}"
        + (" (file limit reached; map is partial)" if truncated else ""),
        f"ENTRY POINTS ({len(entries)}):",
    ]
    sections.extend(f"- {entry}" for entry in entries) if entries else sections.append(
        "(none detected by filename or Python main guard)"
    )
    sections.append(f"CONFIGURATION ({len(root_configs)} root files):")
    sections.extend(f"- {name}" for name in root_configs) if root_configs else sections.append(
        "(no recognized root configuration files)"
    )
    sections.append(
        f"MODULES AND IMPORTS ({len(files)} files; {dependency_count} import references):"
    )
    sections.extend(modules) if modules else sections.append("(no supported source files found)")
    sections.append("NOTE: Imports are static hints, not a complete runtime dependency graph.")
    budget = max_tokens * 4
    output = "\n".join(sections)
    if len(output) > budget:
        output = output[: max(0, budget - 28)].rstrip() + "\n[map truncated to token budget]"
    return output


def register(
    mcp: MCPServer,
    sandbox: Sandbox,
    client_id: str = "workspace-client",
    log_path: Path | None = None,
) -> None:
    if log_path is None:
        log_path = sandbox.root / ".tool_calls.jsonl"

    @audited(
        tool_name="get_project_map",
        role=client_id,
        log_path=log_path,
        summarize=lambda _a, kw: {
            "path": kw.get("path"),
            "max_files": kw.get("max_files"),
            "max_tokens": kw.get("max_tokens"),
        },
    )
    def get_project_map(
        path: Annotated[str, Field(min_length=1, description="Workspace-relative directory to map.")] = ".",
        max_files: Annotated[int, Field(ge=1, le=MAX_FILES, description="Maximum source files to inspect.")] = 150,
        max_tokens: Annotated[int, Field(ge=300, le=MAX_MAP_TOKENS, description="Approximate output token budget.")] = 2500,
    ) -> str:
        """Generate a lightweight static map of modules, imports, entry points, and root configuration."""
        return get_project_map_impl(sandbox, path, max_files, max_tokens)

    mcp.add_tool(get_project_map, name="get_project_map", structured_output=False)
