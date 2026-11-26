"""Tests for the search_files tool."""

import subprocess

import pytest

from server.sandbox import Sandbox, SandboxError
from server.tools.file_tools import list_files_impl
from server.tools.search_tools import search_files_impl


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "workspace"

    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text(
        "def main():\n"
        "    print('hello')\n"
        "    token = 'abc'\n"
        "    return token\n"
    )
    (root / "src" / "utils.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def authenticate(token):\n"
        "    return token\n"
    )
    (root / "README.md").write_text(
        "# Project\n"
        "This project uses authentication.\n"
    )
    (root / "notes.txt").write_text(
        "one\n"
        "two\n"
        "authentication notes\n"
        "three\n"
    )

    # Protected files/directories.
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text(
        "authentication=secret\n"
    )
    (root / ".env").write_text(
        "TOKEN=secret\n"
    )
    (root / "private.pem").write_text(
        "authentication=secret\n"
    )

    return Sandbox(root)


def test_literal_search_finds_matches(ws):
    result = search_files_impl(ws, "authentication")

    assert "README.md:2:" in result
    assert "notes.txt:3:" in result


def test_search_reports_line_numbers(ws):
    result = search_files_impl(ws, "token")

    assert "src/main.py:3:" in result
    assert "src/main.py:4:" in result
    assert "src/utils.py:5:" in result


def test_search_returns_compact_snippets(ws):
    result = search_files_impl(ws, "authentication")

    for line in result.splitlines():
        if ":2:" in line or ":3:" in line:
            assert len(line) < 200


def test_glob_filters_files(ws):
    result = search_files_impl(
        ws,
        "token",
        glob="*.py",
    )

    assert "src/main.py" in result
    assert "src/utils.py" in result
    assert "README.md" not in result
    assert "notes.txt" not in result


def test_path_restricts_search(ws):
    result = search_files_impl(
        ws,
        "token",
        path="src",
    )

    assert "src/main.py" in result
    assert "src/utils.py" in result
    assert "README.md" not in result


def test_regex_search(ws):
    result = search_files_impl(
        ws,
        r"auth\w+",
        regex=True,
    )

    assert "README.md:2:" in result
    assert "src/utils.py:4:" in result


def test_literal_search_does_not_interpret_regex(ws):
    result = search_files_impl(
        ws,
        r"auth\w+",
        regex=False,
    )

    assert result == "No matches."


def test_limit_bounds_results(ws):
    result = search_files_impl(
        ws,
        "token",
        limit=2,
    )

    assert "src/main.py:3:" in result
    assert "src/main.py:4:" in result
    assert "[result limit reached: 2;" in result


def test_protected_files_are_not_searched(ws):
    result = search_files_impl(
        ws,
        "secret",
    )

    assert ".env" not in result
    assert ".git" not in result
    assert "private.pem" not in result


def test_nonexistent_path_is_rejected(ws):
    with pytest.raises(SandboxError):
        search_files_impl(
            ws,
            "token",
            path="does-not-exist",
        )


def test_empty_query_is_rejected(ws):
    with pytest.raises(ValueError):
        search_files_impl(ws, "")


def test_whitespace_query_is_rejected(ws):
    with pytest.raises(ValueError):
        search_files_impl(ws, "   ")


def test_invalid_regex_is_rejected(ws):
    with pytest.raises(ValueError, match="Invalid regular expression"):
        search_files_impl(
            ws,
            "[invalid",
            regex=True,
        )


def test_invalid_limit_is_rejected(ws):
    with pytest.raises(ValueError):
        search_files_impl(
            ws,
            "token",
            limit=0,
        )


def test_limit_above_configured_max_is_rejected(ws):
    with pytest.raises(ValueError):
        search_files_impl(
            ws,
            "token",
            limit=51,
        )


def test_no_match_is_reported(ws):
    result = search_files_impl(
        ws,
        "definitely-not-present",
    )

    assert result == "No matches."


def test_search_single_file(ws):
    result = search_files_impl(
        ws,
        "token",
        path="src/main.py",
    )

    assert "src/main.py:3:" in result
    assert "src/main.py:4:" in result
    assert "src/utils.py" not in result


def test_search_respects_gitignore_and_negation(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    (root / ".gitignore").write_text("*.log\n!keep.log\n", encoding="utf-8")
    (root / "ignored.log").write_text("needle hidden\n", encoding="utf-8")
    (root / "keep.log").write_text("needle visible\n", encoding="utf-8")
    (root / "visible.txt").write_text("needle visible too\n", encoding="utf-8")

    result = search_files_impl(Sandbox(root), "needle")

    assert "keep.log" in result
    assert "visible.txt" in result
    assert "ignored.log" not in result


def test_search_fails_open_when_git_is_unavailable(tmp_path, monkeypatch):
    from server.tools import file_tools

    root = tmp_path / "workspace"
    root.mkdir()
    (root / ".gitignore").write_text("*.log\n", encoding="utf-8")
    (root / "ignored.log").write_text("needle\n", encoding="utf-8")
    monkeypatch.setattr(file_tools.shutil, "which", lambda _name: None)

    result = search_files_impl(Sandbox(root), "needle")

    assert "ignored.log" in result


def test_list_files_respects_gitignore(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    (root / ".gitignore").write_text("*.log\n", encoding="utf-8")
    (root / "ignored.log").write_text("hidden\n", encoding="utf-8")
    (root / "visible.txt").write_text("visible\n", encoding="utf-8")

    result = list_files_impl(Sandbox(root), max_depth=2)

    assert "visible.txt" in result
    assert "ignored.log" not in result


def test_list_files_omits_size_and_line_counts_by_default(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "sample.txt").write_text("one line\n", encoding="utf-8")

    compact = list_files_impl(Sandbox(root), max_depth=1)
    detailed = list_files_impl(Sandbox(root), max_depth=1, include_details=True)

    assert "sample.txt" in compact
    assert " B" not in compact
    assert "lines" not in compact
    assert "sample.txt" in detailed
    assert " B" in detailed
    assert "line" in detailed


def test_missing_path_suggests_close_directory_name(ws):
    with pytest.raises(SandboxError, match=r"Did you mean: 'src'\?"):
        search_files_impl(ws, "token", path="srcc")


def test_missing_nested_path_suggests_full_close_match(ws):
    with pytest.raises(SandboxError, match=r"Did you mean: 'src/main\.py'\?"):
        search_files_impl(ws, "token", path="src/mian.py")


def test_missing_path_without_close_match_points_to_list_files(ws):
    with pytest.raises(SandboxError) as excinfo:
        search_files_impl(ws, "token", path="zzzzzz")

    message = str(excinfo.value)
    assert "Did you mean" not in message
    assert "not found in the workspace root" in message
    assert "list_files" in message


def test_missing_path_never_suggests_protected_names(ws):
    with pytest.raises(SandboxError) as excinfo:
        search_files_impl(ws, "token", path=".evn")

    assert "'.env'" not in str(excinfo.value)


def test_list_files_missing_path_suggests_close_name(ws):
    with pytest.raises(SandboxError, match=r"Did you mean: 'src'\?"):
        list_files_impl(ws, path="srcc")


def test_scan_limit_note_is_added_when_cap_is_hit(tmp_path, monkeypatch):
    from server.tools import file_tools, search_tools

    root = tmp_path / "workspace"
    root.mkdir()
    for name in ("a", "b", "c", "d", "e", "f"):
        (root / f"{name}.txt").write_text("nothing here\n", encoding="utf-8")
    (root / "g.txt").write_text("needle\n", encoding="utf-8")
    monkeypatch.setattr(file_tools, "SCAN_CAP", 3)
    monkeypatch.setattr(search_tools, "SCAN_CAP", 3)

    result = search_files_impl(Sandbox(root), "needle")

    assert result.startswith("No matches.")
    assert "[scan limit reached" in result


def test_scan_limit_note_is_absent_when_everything_was_scanned(ws):
    result = search_files_impl(ws, "authentication")

    assert "scan limit reached" not in result


def test_git_ignored_folders_do_not_use_up_the_scan_cap(tmp_path, monkeypatch):
    from server.tools import file_tools, search_tools

    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    (root / ".gitignore").write_text("dist/\n", encoding="utf-8")
    (root / "dist").mkdir()
    for index in range(20):
        (root / "dist" / f"f{index}.txt").write_text("needle\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "deep.txt").write_text("needle\n", encoding="utf-8")
    monkeypatch.setattr(file_tools, "SCAN_CAP", 6)
    monkeypatch.setattr(search_tools, "SCAN_CAP", 6)

    result = search_files_impl(Sandbox(root), "needle")

    assert "sub/deep.txt" in result
    assert "dist" not in result
    assert "scan limit reached" not in result


@pytest.fixture
def noisy_ws(tmp_path):
    root = tmp_path / "noisy"
    root.mkdir()
    (root / "a_lock.txt").write_text("needle\n" * 30, encoding="utf-8")
    (root / "b.txt").write_text("needle in b\n", encoding="utf-8")
    (root / "c.txt").write_text("needle in c\n", encoding="utf-8")
    return Sandbox(root)


def test_noisy_file_cannot_crowd_out_other_files(noisy_ws):
    result = search_files_impl(noisy_ws, "needle", limit=10)

    assert "b.txt:1:" in result
    assert "c.txt:1:" in result
    assert result.count("a_lock.txt:") == 5 + 1  # 5 matches + the note line
    assert "[a_lock.txt: +25 more matches not shown (per-file limit 5)" in result
    assert "result limit reached" not in result


def test_per_file_limit_is_configurable(noisy_ws):
    result = search_files_impl(noisy_ws, "needle", per_file_limit=1)

    assert result.count("a_lock.txt:") == 1 + 1
    assert "+29 more matches not shown (per-file limit 1)" in result


def test_single_file_search_is_not_per_file_capped(noisy_ws):
    result = search_files_impl(noisy_ws, "needle", path="a_lock.txt")

    assert result.startswith("Found 30 matches:")
    assert "per-file limit" not in result


def test_single_hidden_match_uses_singular_wording(tmp_path):
    root = tmp_path / "one_over"
    root.mkdir()
    (root / "f.txt").write_text("needle\n" * 6, encoding="utf-8")

    result = search_files_impl(Sandbox(root), "needle")

    assert "+1 more match not shown" in result


def test_invalid_per_file_limit_is_rejected(ws):
    with pytest.raises(ValueError, match="per_file_limit"):
        search_files_impl(ws, "token", per_file_limit=0)


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        # A pattern without '/' matches the file name at any depth.
        ("a.py", "*.py", True),
        ("src/a.py", "*.py", True),
        ("src/a.txt", "*.py", False),
        # '*' stays inside one directory when the pattern has a '/'.
        ("src/a.py", "src/*.py", True),
        ("src/a/b.py", "src/*.py", False),
        ("lib/src/a.py", "src/*.py", False),
        # '**' crosses directories.
        ("src/b.py", "src/**/*.py", True),
        ("src/a/b.py", "src/**/*.py", True),
        ("src/a/b/c.py", "src/**/*.py", True),
        ("src/a/b/c.py", "src/**", True),
        ("a.py", "**/*.py", True),
        ("x/y/a.py", "**/*.py", True),
        ("x/y/a.txt", "**/*.py", False),
        # '?' and character classes never match '/'.
        ("src/a.py", "src/?.py", True),
        ("src/ab.py", "src/?.py", False),
        ("src/a1.py", "src/a[0-9].py", True),
        ("src/ax.py", "src/a[!0-9].py", True),
        ("src/a1.py", "src/a[!0-9].py", False),
        # An unterminated '[' is a literal character.
        ("src/a[.py", "src/a[.py", True),
    ],
)
def test_glob_match_is_path_aware(path, pattern, expected):
    from server.tools.file_tools import _glob_match

    assert _glob_match(path, pattern) is expected


def test_search_glob_star_does_not_cross_directories(tmp_path):
    root = tmp_path / "globs"
    (root / "src" / "sub").mkdir(parents=True)
    (root / "src" / "a.py").write_text("needle\n", encoding="utf-8")
    (root / "src" / "sub" / "b.py").write_text("needle\n", encoding="utf-8")
    sandbox = Sandbox(root)

    shallow = search_files_impl(sandbox, "needle", glob="src/*.py")
    recursive = search_files_impl(sandbox, "needle", glob="src/**/*.py")

    assert "src/a.py:1:" in shallow
    assert "src/sub/b.py" not in shallow
    assert "src/a.py:1:" in recursive
    assert "src/sub/b.py:1:" in recursive
