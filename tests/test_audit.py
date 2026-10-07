"""Tests for audit logging."""

import json

from server.audit import audit_tool_call


def test_audit_writes_jsonl_record(tmp_path):
    log_path = tmp_path / "logs" / "tool_calls.jsonl"

    audit_tool_call(
        log_path,
        tool="read_file",
        client="workspace-client",
        success=True,
        arguments={"path": "README.md"},
    )

    lines = log_path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 1

    record = json.loads(lines[0])

    assert record["tool"] == "read_file"
    assert record["client"] == "workspace-client"
    assert record["success"] is True
    assert record["arguments"]["path"] == "README.md"
    assert "timestamp" in record


def test_audit_records_failure(tmp_path):
    log_path = tmp_path / "tool_calls.jsonl"

    audit_tool_call(
        log_path,
        tool="write_file",
        client="workspace-client",
        success=False,
        arguments={"path": ".env"},
        error="Protected path.",
    )

    record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])

    assert record["tool"] == "write_file"
    assert record["success"] is False
    assert record["error"] == "Protected path."


def test_audit_truncates_long_strings(tmp_path):
    log_path = tmp_path / "tool_calls.jsonl"

    audit_tool_call(
        log_path,
        tool="write_file",
        client="workspace-client",
        success=True,
        arguments={
            "path": "example.txt",
            "content": "x" * 1000,
        },
    )

    record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])

    content = record["arguments"]["content"]

    assert len(content) < 1000
    assert content.endswith("...[truncated]")


def test_audit_handles_nested_arguments(tmp_path):
    log_path = tmp_path / "tool_calls.jsonl"

    audit_tool_call(
        log_path,
        tool="read_file",
        client="workspace-client",
        success=True,
        arguments={
            "ranges": [
                {"path": "a.py", "start": 1, "end": 10},
                {"path": "b.py", "start": 20, "end": 30},
            ]
        },
    )

    record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])

    assert len(record["arguments"]["ranges"]) == 2
