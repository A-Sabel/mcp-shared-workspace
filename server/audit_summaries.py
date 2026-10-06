"""Safe argument summaries for audit logging."""

from typing import Any


def path_summary(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    path = kwargs.get("path")
    if path is None and args:
        path = args[0]

    return {"path": path}


def write_summary(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    path = kwargs.get("path")
    content = kwargs.get("content")

    if path is None and args:
        path = args[0]

    if content is None and len(args) > 1:
        content = args[1]

    return {
        "path": path,
        "bytes": (
            len(content.encode("utf-8"))
            if isinstance(content, str)
            else None
        ),
    }


def replace_summary(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    path = kwargs.get("path")
    old = kwargs.get("old")
    new = kwargs.get("new")
    replace_all = kwargs.get("replace_all", False)

    if path is None and args:
        path = args[0]

    if old is None and len(args) > 1:
        old = args[1]

    if new is None and len(args) > 2:
        new = args[2]

    if len(args) > 3:
        replace_all = args[3]

    return {
        "path": path,
        "old_chars": len(old) if isinstance(old, str) else None,
        "new_chars": len(new) if isinstance(new, str) else None,
        "replace_all": replace_all,
    }


def search_summary(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    query = kwargs.get("query")
    path = kwargs.get("path")
    glob = kwargs.get("glob")
    regex = kwargs.get("regex", False)
    limit = kwargs.get("limit")

    if query is None and args:
        query = args[0]

    return {
        "query": query,
        "path": path,
        "glob": glob,
        "regex": regex,
        "limit": limit,
    }


def read_summary(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    ranges = kwargs.get("ranges")

    if ranges is None and args:
        ranges = args[0]

    return {
        "range_count": len(ranges) if isinstance(ranges, list) else None,
    }


def state_summary(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    file = kwargs.get("file")
    entry = kwargs.get("entry")

    if file is None and args:
        file = args[0]

    if entry is None and len(args) > 1:
        entry = args[1]

    return {
        "file": file,
        "entry_chars": len(entry) if isinstance(entry, str) else None,
    }


def git_commit_summary(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    message = kwargs.get("message")
    paths = kwargs.get("paths")

    if message is None and args:
        message = args[0]

    if paths is None and len(args) > 1:
        paths = args[1]

    return {
        "message_chars": (
            len(message)
            if isinstance(message, str)
            else None
        ),
        "path_count": (
            len(paths)
            if isinstance(paths, list)
            else None
        ),
    }