"""Static change-impact analysis for coding agents."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from server.audited_tool import audited
from server.sandbox import Sandbox
from server.tools.git_tools import git_status_impl
from server.tools.project_map_tools import CONFIG_FILES, SOURCE_SUFFIXES, _imports, _walk_sources

MAX_FILES = 300
MAX_RESULTS = 100
MAX_OUTPUT_TOKENS = 4000
TEST_PARTS = {"test", "tests", "__tests__", "spec", "specs"}


def _symbols(path: Path) -> list[str]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if path.suffix.lower() == ".py":
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        return sorted({
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        })

    patterns = (
        r"\bclass\s+([A-Za-z_$][\w$]*)",
        r"\bfunction\s+([A-Za-z_$][\w$]*)",
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=",
        r"\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_][\w]*)",
        r"\bfn\s+([A-Za-z_][\w]*)",
        r"\bfunction\s*&?\s*([A-Za-z_][\w]*)",
    )
    found: set[str] = set()
    for pattern in patterns:
        found.update(re.findall(pattern, source))
    return sorted(found)


def _module_aliases(relative: str) -> set[str]:
    path = Path(relative)
    no_suffix = path.with_suffix("").as_posix()
    aliases = {relative, no_suffix, no_suffix.replace("/", ".")}
    if path.name == "__init__.py":
        package = path.parent.as_posix()
        aliases.update({package, package.replace("/", ".")})
    return {item for item in aliases if item and item != "."}


def _read_source(path: Path) -> str:
    try:
        if path.stat().st_size > 1_000_000:
            return ""
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def get_change_impact_impl(
    sandbox: Sandbox,
    target: str,
    path: str = ".",
    max_files: int = 150,
    max_results: int = 30,
    max_tokens: int = 2500,
) -> str:
    """Identify likely dependencies, references, and tests affected by a change."""
    if not isinstance(target, str) or not target.strip():
        raise ValueError("target must not be empty.")
    if not 1 <= max_files <= MAX_FILES:
        raise ValueError(f"max_files must be between 1 and {MAX_FILES}.")
    if not 1 <= max_results <= MAX_RESULTS:
        raise ValueError(f"max_results must be between 1 and {MAX_RESULTS}.")
    if not 300 <= max_tokens <= MAX_OUTPUT_TOKENS:
        raise ValueError(f"max_tokens must be between 300 and {MAX_OUTPUT_TOKENS}.")

    root = sandbox.resolve(path)
    if not root.is_dir():
        raise ValueError(f"Path {path!r} is not a directory.")

    target_path: Path | None = None
    target_candidate = Path(target)
    looks_like_path = (
        target_candidate.suffix.lower() in SOURCE_SUFFIXES
        or "/" in target
        or "\\" in target
    )
    if looks_like_path:
        candidate = sandbox.resolve(target)
        if not candidate.is_file():
            raise ValueError(f"Target file {target!r} does not exist.")
        if not candidate.is_relative_to(root):
            raise ValueError("target file must be inside the selected path scope.")
        target_path = candidate

    files, truncated = _walk_sources(sandbox, root, max_files)
    if target_path is not None and target_path not in files:
        files.insert(0, target_path)
    relative_files = {item: item.relative_to(root).as_posix() for item in files}

    target_rel = (
        target_path.relative_to(root).as_posix()
        if target_path is not None
        else target.strip()
    )
    target_stem = Path(target_rel).stem if target_path is not None else target.strip()
    target_symbols = _symbols(target_path) if target_path is not None else [target.strip()]
    target_aliases = _module_aliases(target_rel) if target_path is not None else {target.strip()}
    target_aliases.add(target_stem)

    direct: list[str] = []
    dependents: list[str] = []
    references: list[str] = []
    related_tests: list[str] = []

    for source in files:
        rel = relative_files[source]
        imports = _imports(source, root)
        if source == target_path:
            direct = imports[:max_results]

        normalized_imports = {
            value.replace("\\", "/").removesuffix(".py")
            for value in imports
        }
        is_dependent = source != target_path and any(
            value in target_aliases
            or value.endswith("/" + target_stem)
            or value.endswith("." + target_stem)
            for value in normalized_imports
        )
        if is_dependent:
            dependents.append(rel)

        is_test = bool(TEST_PARTS.intersection(Path(rel).parts)) or (
            Path(rel).name.startswith("test_")
            or Path(rel).name.endswith(("_test.py", ".spec.js", ".spec.ts"))
        )
        source_text = _read_source(source)
        matched_symbols = [
            symbol for symbol in target_symbols
            if re.search(rf"(?<![\w$]){re.escape(symbol)}(?![\w$])", source_text)
        ]
        if source != target_path and matched_symbols:
            entry = f"{rel}: {', '.join(matched_symbols[:5])}"
            references.append(entry)
            if is_test:
                related_tests.append(entry)
        elif source != target_path and is_test and is_dependent:
            related_tests.append(f"{rel}: imports target module")

    sections = [
        f"CHANGE IMPACT: {target.strip()}",
        f"SCOPE: {path} | source files inspected: {len(files)}"
        + (" (file limit reached; results are partial)" if truncated else ""),
    ]

    if target_path is not None:
        sections.append(f"TARGET FILE: {target_rel}")
        sections.append("DIRECT IMPORTS:")
        sections.extend(f"- {item}" for item in direct) if direct else sections.append("(no imports detected)")
    else:
        sections.append("TARGET TYPE: symbol/name search (no matching file path found)")

    sections.append(f"LIKELY DEPENDENTS ({len(dependents)}):")
    sections.extend(f"- {item}" for item in dependents[:max_results]) if dependents else sections.append("(none detected)")
    sections.append(f"SYMBOL REFERENCES ({len(references)}):")
    sections.extend(f"- {item}" for item in references[:max_results]) if references else sections.append("(none detected)")
    sections.append(f"RELATED TESTS ({len(related_tests)}):")
    sections.extend(f"- {item}" for item in related_tests[:max_results]) if related_tests else sections.append("(none detected)")
    configs = [
        item.name for item in sorted(root.iterdir(), key=lambda p: p.name.lower())
        if item.is_file() and not item.is_symlink() and item.name in CONFIG_FILES
        and not sandbox.is_protected(item)
    ]
    sections.append(f"RELEVANT ROOT CONFIGURATION ({len(configs)}):")
    sections.extend(f"- {item}" for item in configs) if configs else sections.append("(none detected)")
    try:
        git_status = git_status_impl(sandbox)
    except Exception:
        git_status = "Git status unavailable."
    sections.append("CURRENT GIT STATUS:")
    sections.append(git_status)
    sections.append(
        "CONFIDENCE: Static heuristic only. Imports and text references do not prove runtime impact; "
        "dynamic imports, reflection, generated code, and indirect behavior may be missed."
    )

    output = "\\n".join(sections)
    budget = max_tokens * 4
    if len(output) > budget:
        output = output[: max(0, budget - 30)].rstrip() + "\\n[impact report truncated to token budget]"
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
        tool_name="get_change_impact",
        role=client_id,
        log_path=log_path,
        summarize=lambda _a, kw: {
            "target": kw.get("target"),
            "path": kw.get("path"),
            "max_files": kw.get("max_files"),
        },
    )
    def get_change_impact(
        target: Annotated[str, Field(min_length=1, max_length=500, description="Workspace-relative file path or symbol/function/class name to analyze.")],
        path: Annotated[str, Field(min_length=1, description="Workspace-relative directory to inspect.")] = ".",
        max_files: Annotated[int, Field(ge=1, le=MAX_FILES, description="Maximum source files to inspect.")] = 150,
        max_results: Annotated[int, Field(ge=1, le=MAX_RESULTS, description="Maximum results per report section.")] = 30,
        max_tokens: Annotated[int, Field(ge=300, le=MAX_OUTPUT_TOKENS, description="Approximate output token budget.")] = 2500,
    ) -> str:
        """Estimate code and test impact for a file or symbol before editing."""
        return get_change_impact_impl(
            sandbox, target, path, max_files, max_results, max_tokens
        )

    mcp.add_tool(get_change_impact, name="get_change_impact", structured_output=False)
