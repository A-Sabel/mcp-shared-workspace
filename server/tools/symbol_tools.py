"""Bounded symbol definition and reference search for workspace source files."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from server.audited_tool import audited
from server.sandbox import Sandbox
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


def _source_files(sandbox: Sandbox, path: str, max_files: int) -> tuple[list[Path], bool]:
    root = sandbox.resolve(path)
    if not root.is_dir():
        raise ValueError(f"Path {path!r} is not a directory.")
    return _walk_sources(sandbox, root, max_files)


def _read(path: Path) -> str:
    if path.stat().st_size > MAX_SOURCE_BYTES:
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


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
    if not _IDENTIFIER.fullmatch(symbol):
        raise ValueError("symbol must be a simple identifier.")
    if not 1 <= max_files <= MAX_FILES or not 1 <= max_results <= MAX_RESULTS:
        raise ValueError(f"max_files must be 1..{MAX_FILES} and max_results 1..{MAX_RESULTS}.")
    root = sandbox.resolve(path)
    files, truncated = _source_files(sandbox, path, max_files)
    matches = []
    for file in files:
        source = _read(file)
        if not source:
            continue
        for line, kind in _definitions(source, file.suffix.lower(), symbol):
            matches.append(f"{file.relative_to(root).as_posix()}:{line}: {kind} {symbol}")
    output = [f"SYMBOL DEFINITIONS: {symbol}", f"FILES SCANNED: {len(files)}" + (" (partial: file limit reached)" if truncated else "")]
    output.extend(matches[:max_results] or ["(no definitions detected)"])
    if len(matches) > max_results:
        output.append(f"[{len(matches) - max_results} additional matches omitted]")
    output.append("Python definitions use AST; other supported languages use declaration-pattern matching.")
    return "\n".join(output)


def find_references_impl(sandbox: Sandbox, symbol: str, path: str = ".", max_files: int = 150, max_results: int = 50) -> str:
    if not _IDENTIFIER.fullmatch(symbol):
        raise ValueError("symbol must be a simple identifier.")
    if not 1 <= max_files <= MAX_FILES or not 1 <= max_results <= MAX_RESULTS:
        raise ValueError(f"max_files must be 1..{MAX_FILES} and max_results 1..{MAX_RESULTS}.")
    root = sandbox.resolve(path)
    files, truncated = _source_files(sandbox, path, max_files)
    pattern = re.compile(rf"(?<![\w$]){re.escape(symbol)}(?![\w$])")
    matches = []
    for file in files:
        source = _read(file)
        if not source:
            continue
        for number, line in enumerate(source.splitlines(), 1):
            if pattern.search(line):
                matches.append(f"{file.relative_to(root).as_posix()}:{number}: {line.strip()[:180]}")
    output = [f"SYMBOL REFERENCES: {symbol}", f"FILES SCANNED: {len(files)}" + (" (partial: file limit reached)" if truncated else "")]
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
