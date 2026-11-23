"""Source outline extraction for the MCP shared workspace."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from server.audited_tool import audited
from server.sandbox import Sandbox

MAX_OUTLINE_FILE_BYTES = 512_000
MAX_SYMBOLS = 200
SUPPORTED = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java", ".php", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs"}


def _python_outline(source: str) -> list[str]:
    tree = ast.parse(source)
    lines: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = "class" if isinstance(node, ast.ClassDef) else "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            lines.append(f"{node.lineno}: {kind} {node.name}")
        elif isinstance(node, ast.Import):
            names = ", ".join(alias.name for alias in node.names)
            lines.append(f"{node.lineno}: import {names}")
        elif isinstance(node, ast.ImportFrom):
            names = ", ".join(alias.name for alias in node.names)
            lines.append(f"{node.lineno}: from {node.module or ''} import {names}")
    return sorted(lines, key=lambda item: int(item.split(":", 1)[0]))


DECLARATION_PATTERNS = (
    ("class", re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+[A-Za-z_$][\w$]*")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+[A-Za-z_$][\w$]*")),
    ("method", re.compile(r"^\s*(?:public|private|protected|static|async|final|override|\s)+\s*[\w<>\[\],.?]+\s+[A-Za-z_$][\w$]*\s*\([^;]*\)\s*(?:\{|=>|;)?$")),
    ("import", re.compile(r"^\s*(?:import|from|#include|use)\s+.+")),
    ("const", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*(?::[^=]+)?=")),
)


def get_file_outline_impl(sandbox: Sandbox, path: str, max_symbols: int = 100) -> str:
    safe = sandbox.resolve(path)
    if not safe.is_file():
        raise ValueError(f"Path {path!r} is not a file.")
    if safe.suffix.lower() not in SUPPORTED:
        raise ValueError(f"Unsupported source type {safe.suffix or '(no extension)'}. Supported: {', '.join(sorted(SUPPORTED))}.")
    size = safe.stat().st_size
    if size > MAX_OUTLINE_FILE_BYTES:
        raise ValueError(f"File exceeds the {MAX_OUTLINE_FILE_BYTES}-byte outline limit.")
    if not 1 <= max_symbols <= MAX_SYMBOLS:
        raise ValueError(f"max_symbols must be between 1 and {MAX_SYMBOLS}.")
    try:
        source = safe.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ValueError("File is not valid UTF-8 source text.") from None
    if safe.suffix.lower() == ".py":
        try:
            symbols = _python_outline(source)
        except SyntaxError as exc:
            raise ValueError(f"Cannot parse Python source: {exc.msg} at line {exc.lineno}.") from None
    else:
        symbols = []
        for number, line in enumerate(source.splitlines(), 1):
            for kind, pattern in DECLARATION_PATTERNS:
                if pattern.search(line):
                    symbols.append(f"{number}: {kind} {line.strip()}")
                    break
    shown = symbols[:max_symbols]
    output = [f"OUTLINE: {sandbox.relative(safe)}", f"SYMBOLS: {len(symbols)} (showing {len(shown)})"]
    output.extend(shown or ["(no declarations found)"])
    if len(symbols) > len(shown):
        output.append(f"[{len(symbols) - len(shown)} additional symbols omitted]")
    return "\n".join(output)


def register(mcp: MCPServer, sandbox: Sandbox, client_id: str = "workspace-client", log_path: Path | None = None) -> None:
    if log_path is None:
        log_path = sandbox.root / ".tool_calls.jsonl"

    @audited(tool_name="get_file_outline", role=client_id, log_path=log_path,
             summarize=lambda _a, kw: {"path": kw.get("path"), "max_symbols": kw.get("max_symbols")})
    def get_file_outline(
        path: Annotated[str, Field(min_length=1, description="Workspace-relative source file path.")],
        max_symbols: Annotated[int, Field(ge=1, le=MAX_SYMBOLS, description="Maximum declarations to return.")] = 100,
    ) -> str:
        """Extract imports and top-level code declarations without returning full file contents."""
        return get_file_outline_impl(sandbox, path, max_symbols)

    mcp.add_tool(get_file_outline, name="get_file_outline", structured_output=False)
