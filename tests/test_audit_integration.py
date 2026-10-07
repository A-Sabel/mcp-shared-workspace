import json
from pathlib import Path

from server.audit import audit_tool_call
from server.audit_summaries import (
    git_commit_summary,
    read_summary,
    replace_summary,
    search_summary,
    write_summary,
)


def read_audit_records(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_audit_success_record(tmp_path: Path):
    log_path = tmp_path / "tool_calls.jsonl"

    arguments = write_summary(
        (),
        {
            "path": "notes.txt",
            "content": "SECRET_CONTENT_SHOULD_NOT_APPEAR",
        },
    )

    audit_tool_call(
        log_path,
        tool="write_file",
        client="workspace-client",
        success=True,
        arguments=arguments,
    )

    records = read_audit_records(log_path)

    assert len(records) == 1

    record = records[0]

    assert record["tool"] == "write_file"
    assert record["client"] == "workspace-client"
    assert record["success"] is True

    # File contents must never be logged.
    raw_log = log_path.read_text(encoding="utf-8")

    assert "SECRET_CONTENT_SHOULD_NOT_APPEAR" not in raw_log
    assert record["arguments"]["path"] == "notes.txt"
    assert record["arguments"]["bytes"] == len(
        "SECRET_CONTENT_SHOULD_NOT_APPEAR".encode("utf-8")
    )


def test_audit_failure_record(tmp_path: Path):
    log_path = tmp_path / "tool_calls.jsonl"

    audit_tool_call(
        log_path,
        tool="delete_file",
        client="workspace-client",
        success=False,
        arguments={"path": "important.txt"},
        error="Protected path cannot be deleted.",
    )

    records = read_audit_records(log_path)

    assert len(records) == 1

    record = records[0]

    assert record["tool"] == "delete_file"
    assert record["client"] == "workspace-client"
    assert record["success"] is False
    assert record["error"] == "Protected path cannot be deleted."


def test_audit_multiple_records_are_valid_jsonl(tmp_path: Path):
    log_path = tmp_path / "tool_calls.jsonl"

    for tool in ("list_files", "read_file", "search_files"):
        audit_tool_call(
            log_path,
            tool=tool,
            client="workspace-client",
            success=True,
            arguments={"example": "value"},
        )

    records = read_audit_records(log_path)

    assert len(records) == 3

    assert [record["tool"] for record in records] == [
        "list_files",
        "read_file",
        "search_files",
    ]


def test_audit_summaries_remove_sensitive_content():
    write_args = write_summary(
        (),
        {
            "path": "secret.txt",
            "content": "SUPER_SECRET_CONTENT",
        },
    )

    assert write_args == {
        "path": "secret.txt",
        "bytes": len("SUPER_SECRET_CONTENT".encode("utf-8")),
    }

    read_args = read_summary(
        (),
        {
            "path": "secret.txt",
            "ranges": [
                {"start": 1, "end": 10},
                {"start": 20, "end": 30},
            ],
        },
    )

    assert read_args == {
        "range_count": 2,
    }

    replace_args = replace_summary(
        (),
        {
            "path": "secret.txt",
            "old": "OLD_SECRET",
            "new": "NEW_SECRET",
            "replace_all": True,
        },
    )

    assert replace_args == {
        "path": "secret.txt",
        "old_chars": 10,
        "new_chars": 10,
        "replace_all": True,
    }


def test_search_summary_keeps_query_but_not_unbounded_data():
    args = search_summary(
        (),
        {
            "query": "TODO",
            "path": "src",
            "glob": "*.py",
            "regex": False,
            "limit": 50,
        },
    )

    assert args == {
        "query": "TODO",
        "path": "src",
        "glob": "*.py",
        "regex": False,
        "limit": 50,
    }


def test_git_commit_summary_does_not_log_full_message():
    args = git_commit_summary(
        (),
        {
            "message": "Implement extremely important feature",
            "paths": ["server/main.py", "README.md"],
        },
    )

    assert args == {
        "message_chars": len("Implement extremely important feature"),
        "path_count": 2,
    }


def test_audit_truncates_large_string_values(tmp_path: Path):
    log_path = tmp_path / "tool_calls.jsonl"

    audit_tool_call(
        log_path,
        tool="example",
        client="workspace-client",
        success=True,
        arguments={"value": "A" * 1000},
    )

    records = read_audit_records(log_path)

    logged_value = records[0]["arguments"]["value"]

    assert logged_value.endswith("...[truncated]")
    assert len(logged_value) == 214
