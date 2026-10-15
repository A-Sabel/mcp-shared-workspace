"""Tests for bounded, sandboxed read_file ranges."""

import asyncio
import json
from pathlib import Path

import pytest
from mcp.server.mcpserver import MCPServer

from server.sandbox import Sandbox
from server.tools.file_tools import (
    MAX_READ_LINES,
    MAX_READ_RANGES,
    read_file_impl,
    read_file_result_impl,
    register,
)


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "one.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    (root / "two.txt").write_text("uno\ndos\n", encoding="utf-8")
    return Sandbox(root)


def test_single_range_has_compact_one_based_line_numbers(sandbox):
    assert read_file_impl(sandbox, [{"path": "one.txt", "start": 2, "end": 3}]) == (
        "one.txt:2-3\n2: beta\n3: gamma"
    )


def test_non_contiguous_ranges_across_files_keep_requested_order(sandbox):
    result = read_file_impl(
        sandbox,
        [
            {"path": "one.txt", "start": 1, "end": 1},
            {"path": "two.txt", "start": 2, "end": 2},
            {"path": "one.txt", "start": 3, "end": 3},
        ],
    )
    assert result == (
        "one.txt:1-1\n1: alpha\n\n" "two.txt:2-2\n2: dos\n\n" "one.txt:3-3\n3: gamma"
    )


def test_maximum_range_length_is_allowed(sandbox):
    content = "".join(f"line {i}\n" for i in range(1, MAX_READ_LINES + 1))
    (sandbox.root / "many.txt").write_text(content, encoding="utf-8")
    result = read_file_impl(
        sandbox,
        [{"path": "many.txt", "start": 1, "end": MAX_READ_LINES}],
    )
    assert result.startswith("many.txt:1-200\n1: line 1")
    assert result.endswith("200: line 200")


def test_requested_range_past_eof_returns_available_lines(sandbox):
    assert read_file_impl(sandbox, [{"path": "two.txt", "start": 2, "end": 10}]) == (
        "two.txt:2-10\n2: dos"
    )


def test_range_start_past_eof_has_explicit_empty_result(sandbox):
    assert read_file_impl(sandbox, [{"path": "two.txt", "start": 8, "end": 9}]) == (
        "two.txt:8-9\n(no lines in requested range)"
    )


@pytest.mark.parametrize(
    "ranges, message",
    [
        ([], "At least one range"),
        (
            [{"path": "one.txt", "start": 1, "end": 1}] * (MAX_READ_RANGES + 1),
            "At most 5 ranges",
        ),
        (
            [{"path": "one.txt", "start": 1, "end": MAX_READ_LINES + 1}],
            "at most 200 lines",
        ),
        (
            [{"path": "one.txt", "start": 3, "end": 2}],
            "end must be greater than or equal",
        ),
        ([{"path": "one.txt", "start": 0, "end": 2}], "Invalid range"),
        ([{"path": "one.txt", "start": 1, "end": 2, "other": 1}], "Invalid range"),
        ([{"path": "one.txt", "start": True, "end": 2}], "Invalid range"),
        ([{"path": "one.txt", "start": "1", "end": 2}], "Invalid range"),
        ([{"path": "one.txt", "start": 1}], "Invalid range"),
    ],
)
def test_invalid_ranges_fail_cleanly(sandbox, ranges, message):
    with pytest.raises(ValueError, match=message):
        read_file_impl(sandbox, ranges)


def test_ranges_must_be_a_list(sandbox):
    with pytest.raises(ValueError, match="ranges must be a list"):
        read_file_impl(sandbox, {"path": "one.txt", "start": 1, "end": 1}) # type: ignore


@pytest.mark.parametrize("path", ["missing.txt", "subdir"])
def test_missing_file_and_directory_are_rejected(sandbox, path):
    (sandbox.root / "subdir").mkdir()
    with pytest.raises(ValueError, match="does not exist|not a file"):
        read_file_impl(sandbox, [{"path": path, "start": 1, "end": 1}])


@pytest.mark.parametrize(
    "path", ["../outside.txt", ".env", "credentials.pem", ".git/config"]
)
def test_sandbox_rejects_traversal_and_protected_paths(sandbox, path):
    with pytest.raises(ValueError):
        read_file_impl(sandbox, [{"path": path, "start": 1, "end": 1}])


def test_invalid_utf8_is_reported_as_text_read_error(sandbox):
    (sandbox.root / "binary.bin").write_bytes(b"\xff\xfe")
    with pytest.raises(ValueError, match="not valid UTF-8 text"):
        read_file_impl(sandbox, [{"path": "binary.bin", "start": 1, "end": 1}])


class CountingTextReader:
    def __init__(self, stream):
        self.stream = stream
        self.lines_read = 0
        self.bytes_read = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def __iter__(self):
        for line in self.stream:
            self.lines_read += 1
            self.bytes_read += len(line.encode("utf-8"))
            yield line


@pytest.mark.parametrize(
    "count_total_lines, expected_lines_read, expected_total",
    [(False, 161, None), (True, 600, 600)],
)
def test_read_result_stops_early_unless_exact_total_requested(
    sandbox, monkeypatch, count_total_lines, expected_lines_read, expected_total
):
    fixture = Path(__file__).parent / "fixtures" / "read_file_large.txt"
    fixture_lines = fixture.read_text(encoding="utf-8").splitlines(keepends=True)
    target = (sandbox.root / "large.txt").resolve()
    target.write_text("".join(fixture_lines), encoding="utf-8")

    original_open = Path.open
    readers = []

    def tracked_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        if path.resolve() == target:
            reader = CountingTextReader(stream)
            readers.append(reader)
            return reader
        return stream

    monkeypatch.setattr(Path, "open", tracked_open)
    response = read_file_result_impl(
        sandbox,
        [{"path": "large.txt", "start": 150, "end": 160}],
        count_total_lines=count_total_lines,
    )
    result = json.loads(response)["ranges"][0]

    assert readers[0].lines_read == expected_lines_read
    assert readers[0].bytes_read == sum(
        len(line.encode("utf-8")) for line in fixture_lines[:expected_lines_read]
    )
    assert result["total_lines"] == expected_total
    assert result["has_more"] is True
    assert result["next_start_line"] == 161
    assert result["content"].endswith("160: " + fixture_lines[159].rstrip("\n"))


def test_read_file_is_registered_for_authenticated_client(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    mcp = MCPServer("test-client")

    register(mcp, Sandbox(root))

    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert "read_file" in names
