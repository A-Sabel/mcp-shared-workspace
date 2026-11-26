"""Bounded symbol definition and reference search for workspace source files."""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from server.audited_tool import audited
from server.sandbox import Sandbox, SandboxError
from server.tools.file_tools import _missing_path_message
from server.tools.project_map_tools import _walk_sources

MAX_FILES = 300
MAX_RESULTS = 100
MAX_SOURCE_BYTES = 1_000_000
_IDENTIFIER = re.compile(r"^[A-Za-z_$][\w$]*$")
_DECLARATIONS = (
    re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*="),
    re.compile(r"\b(?:def|async\s+def)\s+([A-Za-z_][\w]*)"),
    re.compile(r"\b(?:public|private|protected|static|final|abstract)\s+[\w<>\[\],.?]+\s+([A-Za-z_$][\w$]*)\s*\("),
    re.compile(r"\bfn\s+([A-Za-z_][\w]*)"),
    re.compile(r"\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_][\w]*)"),
)


def _validate(symbol: str, max_files: int, max_results: int) -> None:
    if not isinstance(symbol, str) or not _IDENTIFIER.fullmatch(symbol):
        shown = str(symbol)
        if len(shown) > 60:
            shown = shown[:57] + "..."
        raise ValueError(
            "symbol must be a simple identifier (letters, digits, '_' or '$', "
            f"not starting with a digit); got {shown!r}. For phrases, dotted "
            "names such as 'a.b', or other text, use search_files instead."
        )
    if not 1 <= max_files <= MAX_FILES or not 1 <= max_results <= MAX_RESULTS:
        raise ValueError(f"max_files must be 1..{MAX_FILES} and max_results 1..{MAX_RESULTS}.")


def _source_files(
    sandbox: Sandbox, path: str, max_files: int
) -> tuple[list[Path], bool, Callable[[Path], str]]:
    """Return (files, truncated, label) for a directory or a single file.

    ``label`` renders a file path for output: relative to the searched
    directory, or workspace-relative when one file was named directly.
    """
    root = sandbox.resolve(path)
    if not root.exists():
        raise SandboxError(_missing_path_message(sandbox, path))
    if root.is_file():
        if sandbox.is_protected(root):
            raise SandboxError(f"Path {path!r} is protected and cannot be searched.")
        return [root], False, sandbox.relative
    if not root.is_dir():
        raise SandboxError(f"Path {path!r} is not a file or directory.")
    files, truncated = _walk_sources(sandbox, root, max_files)
    return files, truncated, lambda file: file.relative_to(root).as_posix()


def _scan_status(scanned: int, skipped: int, truncated: bool) -> str:
    status = f"FILES SCANNED: {scanned}"
    if truncated:
        status += " (partial: file limit reached)"
    if skipped:
        status += f"; {skipped} skipped (over 1 MB or not valid UTF-8)"
    return status


def _read(path: Path) -> str | None:
    """Return file text, or None when the file is too large or unreadable."""
    try:
        if path.stat().st_size > MAX_SOURCE_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _definitions(source: str, suffix: str, name: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    if suffix == ".py":
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return found
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                found.append((node.lineno, kind))
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                    found.append((node.lineno, "variable"))
        return sorted(set(found))
    for number, line in enumerate(source.splitlines(), 1):
        for pattern in _DECLARATIONS:
            match = pattern.search(line)
            if match and match.group(1) == name:
                found.append((number, "declaration"))
                break
    return found


def find_symbol_impl(sandbox: Sandbox, symbol: str, path: str = ".", max_files: int = 150, max_results: int = 30) -> str:
    _validate(symbol, max_files, max_results)
    files, truncated, label = _source_files(sandbox, path, max_files)
    matches = []
    scanned = skipped = 0
    for file in files:
        source = _read(file)
        if source is None:
            skipped += 1
            continue
        scanned += 1
        for line, kind in _definitions(source, file.suffix.lower(), symbol):
            matches.append(f"{label(file)}:{line}: {kind} {symbol}")
    output = [f"SYMBOL DEFINITIONS: {symbol}", _scan_status(scanned, skipped, truncated)]
    output.extend(matches[:max_results] or ["(no definitions detected)"])
    if len(matches) > max_results:
        output.append(f"[{len(matches) - max_results} additional matches omitted]")
    output.append("Python definitions use AST; other supported languages use declaration-pattern matching.")
    return "\n".join(output)


def find_references_impl(sandbox: Sandbox, symbol: str, path: str = ".", max_files: int = 150, max_results: int = 50) -> str:
    _validate(symbol, max_files, max_results)
    files, truncated, label = _source_files(sandbox, path, max_files)
    pattern = re.compile(rf"(?<![\w$]){re.escape(symbol)}(?![\w$])")
    matches = []
    scanned = skipped = 0
    for file in files:
        source = _read(file)
        if source is None:
            skipped += 1
            continue
        scanned += 1
        for number, line in enumerate(source.splitlines(), 1):
            if pattern.search(line):
                matches.append(f"{label(file)}:{number}: {line.strip()[:180]}")
    output = [f"SYMBOL REFERENCES: {symbol}", _scan_status(scanned, skipped, truncated)]
    output.extend(matches[:max_results] or ["(no references detected)"])
    if len(matches) > max_results:
        output.append(f"[{len(matches) - max_results} additional matches omitted]")
    output.append("References are lexical text matches, not guaranteed semantic references; comments, strings, overloads, and shadowed names may appear.")
    return "\n".join(output)


def register(mcp: MCPServer, sandbox: Sandbox, client_id: str = "workspace-client", log_path: Path | None = None) -> None:
    if log_path is None:
        log_path = sandbox.root / ".tool_calls.jsonl"

    @audited(tool_name="find_symbol", role=client_id, log_path=log_path,
             summarize=lambda _a, kw: {"symbol": kw.get("symbol"), "path": kw.get("path")})
    def find_symbol(
        symbol: Annotated[str, Field(min_length=1, max_length=128, description="Identifier to locate.")],
        path: Annotated[str, Field(min_length=1, description="Workspace-relative source directory.")] = ".",
        max_files: Annotated[int, Field(ge=1, le=MAX_FILES)] = 150,
        max_results: Annotated[int, Field(ge=1, le=MAX_RESULTS)] = 30,
    ) -> str:
        """Find likely declarations of a symbol in supported source files."""
        return find_symbol_impl(sandbox, symbol, path, max_files, max_results)

    @audited(tool_name="find_references", role=client_id, log_path=log_path,
             summarize=lambda _a, kw: {"symbol": kw.get("symbol"), "path": kw.get("path")})
    def find_references(
        symbol: Annotated[str, Field(min_length=1, max_length=128, description="Identifier to search for.")],
        path: Annotated[str, Field(min_length=1, description="Workspace-relative source directory.")] = ".",
        max_files: Annotated[int, Field(ge=1, le=MAX_FILES)] = 150,
        max_results: Annotated[int, Field(ge=1, le=MAX_RESULTS)] = 50,
    ) -> str:
        """Find lexical references to a symbol in supported source files."""
        return find_references_impl(sandbox, symbol, path, max_files, max_results)

    mcp.add_tool(find_symbol, name="find_symbol", structured_output=False)
    mcp.add_tool(find_references, name="find_references", structured_output=False)
