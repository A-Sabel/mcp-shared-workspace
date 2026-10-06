from __future__ import annotations

READER = "reader"
WRITER = "writer"

ROLES = (READER, WRITER)

_RANK = {
    READER: 0,
    WRITER: 1,
}

# Minimum role required for each tool.
TOOL_ROLES: dict[str, str] = {
    "list_files": READER,
    "read_file": READER,
    "search_files": READER,
    "append_state": READER,
    "git_status": READER,
    "git_diff": READER,
    "write_file": WRITER,
    "str_replace": WRITER,
    "delete_file": WRITER,
    "git_commit": WRITER,
}


def is_allowed(tool: str, role: str) -> bool:
    if tool not in TOOL_ROLES:
        raise KeyError(f"Tool {tool!r} is not classified in TOOL_ROLES.")

    if role not in _RANK:
        raise ValueError(f"Unknown role {role!r}; expected one of {ROLES}.")

    return _RANK[role] >= _RANK[TOOL_ROLES[tool]]