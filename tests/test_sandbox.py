"""Sandbox tests: traversal, absolute paths, symlinks, protected names."""

from pathlib import Path

import pytest

from server.sandbox import MAX_PATH_LEN, Sandbox, SandboxError


@pytest.fixture
def ws(tmp_path: Path) -> Sandbox:
    """A workspace with a sibling directory sharing its name prefix."""
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("print('hi')\n")
    (root / "README.md").write_text("# hi\n")
    (tmp_path / "secret.txt").write_text("outside secret")
    (tmp_path / "workspace-evil").mkdir()
    (tmp_path / "workspace-evil" / "loot.txt").write_text("loot")
    return Sandbox(root)


def _symlink(link: Path, target: Path | str) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported here")


# ---------------------------------------------------------------- accepted


def test_existing_file(ws):
    assert ws.resolve("src/main.py") == ws.root / "src" / "main.py"


def test_root_dot_allowed_for_reads(ws):
    assert ws.resolve(".") == ws.root


def test_new_file_in_existing_dir(ws):
    assert ws.resolve("src/new.py", for_write=True) == ws.root / "src" / "new.py"


def test_new_nested_path(ws):
    assert ws.resolve("a/b/c.txt", for_write=True) == ws.root / "a" / "b" / "c.txt"


def test_dot_segments_that_stay_inside(ws):
    assert ws.resolve("src/../README.md") == ws.root / "README.md"


@pytest.mark.parametrize("rel", [".", "src/.."])
def test_root_is_not_writable(ws, rel):
    with pytest.raises(SandboxError):
        ws.resolve(rel, for_write=True)


# ---------------------------------------------------------------- traversal


@pytest.mark.parametrize(
    "bad",
    [
        "..",
        "../secret.txt",
        "../../etc/passwd",
        "src/../../secret.txt",
        "src/../..",
        "./../secret.txt",
        "a/b/../../../secret.txt",
    ],
)
def test_traversal_rejected(ws, bad):
    with pytest.raises(SandboxError):
        ws.resolve(bad)


def test_sibling_directory_with_same_prefix_rejected(ws):
    # A string startswith() check would wrongly accept this.
    with pytest.raises(SandboxError):
        ws.resolve("../workspace-evil/loot.txt")


def test_error_does_not_leak_host_paths(ws):
    with pytest.raises(SandboxError) as exc:
        ws.resolve("../secret.txt")
    assert str(ws.root) not in str(exc.value)


# ---------------------------------------------------------- absolute / odd


def test_absolute_paths_rejected(ws):
    outside = ws.root.parent / "secret.txt"
    for bad in ("/etc/passwd", str(outside), str(ws.root / "README.md")):
        with pytest.raises(SandboxError):
            ws.resolve(bad)


@pytest.mark.parametrize(
    "bad",
    ["..\\secret.txt", "C:\\Windows\\system32", "C:/Windows", "\\\\server\\share\\x", "src\\main.py"],
)
def test_windows_style_paths_rejected(ws, bad):
    with pytest.raises(SandboxError):
        ws.resolve(bad)


@pytest.mark.parametrize("bad", ["src/main.py\x00.txt", "a\nb", "tab\there"])
def test_control_characters_rejected(ws, bad):
    with pytest.raises(SandboxError):
        ws.resolve(bad)


@pytest.mark.parametrize("bad", ["", None, 123, ["src"]])
def test_empty_or_non_string_rejected(ws, bad):
    with pytest.raises(SandboxError):
        ws.resolve(bad)


def test_overlong_path_rejected(ws):
    with pytest.raises(SandboxError):
        ws.resolve("a" * (MAX_PATH_LEN + 1))


@pytest.mark.parametrize("name", ["%2e%2e/secret.txt", "..%2fsecret.txt", "%2e%2e%2fsecret.txt"])
def test_percent_encoding_is_not_decoded(ws, name):
    # Treated as ordinary (odd) file names, so they stay inside the workspace.
    result = ws.resolve(name)
    assert result.is_relative_to(ws.root)
    assert result != ws.root.parent / "secret.txt"


@pytest.mark.parametrize(
    "bad",
    [
        ".env::$DATA",       # alternate data stream on Windows
        "secret.txt:stream",
        "C:foo",
        "key.pem ",          # trailing space is stripped by Windows
        ".git.",
        ".env.",
        "dir /file.txt",
        "...",
        "nul",               # Windows device names
        "CON.txt",
        "src/aux",
        "com1.log",
        "LPT9",
    ],
)
def test_windows_bypass_names_rejected(ws, bad):
    with pytest.raises(SandboxError):
        ws.resolve(bad)
    with pytest.raises(SandboxError):
        ws.resolve(bad, for_write=True)


@pytest.mark.parametrize(
    "ok", ["console.log", "connection.py", "auxiliary.md", "null.txt", "./src/main.py", "src//main.py"]
)
def test_similar_but_safe_names_allowed(ws, ok):
    assert ws.resolve(ok).is_relative_to(ws.root)


# ---------------------------------------------------------------- symlinks


def test_symlinked_dir_to_outside_rejected(ws):
    _symlink(ws.root / "link", ws.root.parent / "workspace-evil")
    for bad in ("link", "link/loot.txt", "link/new.txt"):
        with pytest.raises(SandboxError):
            ws.resolve(bad)


def test_symlinked_file_to_outside_rejected(ws):
    _symlink(ws.root / "s.txt", ws.root.parent / "secret.txt")
    with pytest.raises(SandboxError):
        ws.resolve("s.txt")


def test_dangling_symlink_to_outside_rejected(ws):
    _symlink(ws.root / "dangling", ws.root.parent / "does-not-exist")
    with pytest.raises(SandboxError):
        ws.resolve("dangling", for_write=True)


def test_symlink_staying_inside_is_allowed(ws):
    _symlink(ws.root / "alias.py", ws.root / "src" / "main.py")
    assert ws.resolve("alias.py") == ws.root / "src" / "main.py"


def test_symlink_to_protected_file_rejected(ws):
    (ws.root / ".env").write_text("TOKEN=x")
    _symlink(ws.root / "innocent.txt", ws.root / ".env")
    with pytest.raises(SandboxError):
        ws.resolve("innocent.txt")


def test_symlink_loop_never_escapes_or_crashes(ws):
    _symlink(ws.root / "loop", "loop")
    try:
        result = ws.resolve("loop")
    except SandboxError:
        return
    assert result.is_relative_to(ws.root)


# ------------------------------------------------------------- protected


@pytest.mark.parametrize(
    "bad",
    [
        ".env",
        "sub/.env",
        ".env.local",
        ".ENV",
        "key.pem",
        "certs/server.PEM",
        "id_rsa",
        "id_rsa.pub",
        "backup_id_rsa_old",
        ".git",
        ".git/config",
        "src/.git/HEAD",
        ".GIT/config",
        ".trash",
        ".trash/old.txt",
    ],
)
def test_protected_paths_rejected_for_read_and_write(ws, bad):
    with pytest.raises(SandboxError):
        ws.resolve(bad)
    with pytest.raises(SandboxError):
        ws.resolve(bad, for_write=True)


@pytest.mark.parametrize(
    "ok",
    [
        "environment.md",
        "README.md",
        "pem.txt",
        "notes.git",
        ".github/workflows/ci.yml",
        "gitignore.txt",
        "id_rs.txt",
        "PROJECT_STATE.md",
    ],
)
def test_lookalike_names_allowed(ws, ok):
    assert ws.resolve(ok, for_write=True).is_relative_to(ws.root)


def test_is_protected_for_walkers(ws):
    assert ws.is_protected(ws.root / ".git" / "config")
    assert ws.is_protected(ws.root / "key.pem")
    assert ws.is_protected(ws.root.parent / "secret.txt")  # outside the root
    assert not ws.is_protected(ws.root / "src" / "main.py")


# ------------------------------------------------------------ construction


def test_relative_helper(ws):
    assert ws.relative(ws.root / "src" / "main.py") == "src/main.py"
    assert ws.relative(ws.root) == "."


def test_root_must_be_existing_directory(tmp_path):
    with pytest.raises(SandboxError):
        Sandbox(tmp_path / "missing")
    (tmp_path / "file.txt").write_text("x")
    with pytest.raises(SandboxError):
        Sandbox(tmp_path / "file.txt")


def test_root_given_as_symlink_is_resolved(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    _symlink(tmp_path / "linked", real)
    assert Sandbox(tmp_path / "linked").root == real.resolve()


def test_trash_dir_is_inside_root_but_not_resolvable(ws):
    assert ws.trash_dir == ws.root / ".trash"
    with pytest.raises(SandboxError):
        ws.resolve(".trash/x.txt")