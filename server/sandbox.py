"""Workspace sandbox: the one gate every tool path must pass through.

Every tool calls ``Sandbox.resolve()`` before touching the disk. A path is
accepted only if it:

  1. is relative, with no control characters, backslashes or drive letters;
  2. resolves (after following symlinks) to a location inside the workspace
     root, checked with ``is_relative_to`` rather than a string prefix;
  3. does not touch a protected name (.git, .trash, .env, *.pem, *id_rsa*).

Error messages echo the *requested* path, never the absolute location, so a
rejected call does not reveal anything about the host filesystem.

Known limits (list these in the report's threat section):
  * A hard link inside the workspace to an outside file cannot be detected
    by path checks.
  * A symlink swapped in between the check and the file operation (TOCTOU)
    is not prevented. The workspace should only be writable by trusted
    processes.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path, PurePosixPath, PureWindowsPath

MAX_PATH_LEN = 512

# Directory names that are never accessible through any tool. The server
# itself manages .git (via git tools) and .trash (via delete_file).
PROTECTED_DIRS = frozenset({".git", ".trash"})

# File-name patterns (lower-case, matched case-insensitively) that are never
# readable or writable, so secrets cannot leak through read_file/search_files.
PROTECTED_NAME_PATTERNS = (".env", ".env.*", "*.pem", "*id_rsa*")

# Windows quirks that can bypass name checks when the server runs on Windows:
# alternate data streams (".env::$DATA"), trailing dots/spaces ("key.pem "),
# and device names (CON, NUL, COM1...). Rejected on every OS for consistency.
_WINDOWS_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)

# The only files append_state may write to.
HANDOFF_FILES = ("PROJECT_STATE.md", "PLAN_LOG.md", "CHECKPOINTS.md", "DECISIONS.md")


class SandboxError(ValueError):
    """A path was rejected. The message is safe to show to the agent."""


class Sandbox:
    def __init__(self, root: str | Path) -> None:
        root_path = Path(root)
        if not root_path.is_dir():
            raise SandboxError("Workspace root does not exist or is not a directory.")
        self.root: Path = root_path.resolve()

    # ------------------------------------------------------------------ API

    @property
    def trash_dir(self) -> Path:
        """Where delete_file moves files. Not reachable through resolve()."""
        return self.root / ".trash"

    def resolve(self, rel: str, *, for_write: bool = False) -> Path:
        """Validate a requested path and return its absolute, resolved form.

        The path need not exist (so tools can create new files), but every
        existing component is resolved, so symlinks cannot be used to escape.
        Use "." for the workspace root. The root itself is never writable.
        """
        self._check_syntax(rel)

        try:
            resolved = (self.root / rel).resolve()
        except (OSError, RuntimeError):  # e.g. symlink loop
            raise SandboxError(f"Cannot resolve path {rel!r}.") from None

        if not resolved.is_relative_to(self.root):
            raise SandboxError(f"Path {rel!r} is outside the workspace.")

        parts = resolved.relative_to(self.root).parts
        if for_write and not parts:
            raise SandboxError("The workspace root cannot be modified.")
        if self._has_protected_part(parts):
            raise SandboxError(f"Path {rel!r} is protected and cannot be accessed.")
        return resolved

    def is_protected(self, path: Path) -> bool:
        """True if an absolute path is outside the root or hits a protected name.

        Directory walkers (list_files, search_files, repo_map) use this to skip
        entries instead of raising.
        """
        try:
            parts = path.relative_to(self.root).parts
        except ValueError:
            return True
        return self._has_protected_part(parts)

    def relative(self, path: Path) -> str:
        """Workspace-relative POSIX string for output and logs ('.' for root)."""
        return path.relative_to(self.root).as_posix()

    # ------------------------------------------------------------- internals

    @staticmethod
    def _check_syntax(rel: object) -> None:
        if not isinstance(rel, str):
            raise SandboxError("Path must be a string.")
        if not rel:
            raise SandboxError("Path is empty; use '.' for the workspace root.")
        if len(rel) > MAX_PATH_LEN:
            raise SandboxError(f"Path is longer than {MAX_PATH_LEN} characters.")
        if any(ord(ch) < 32 for ch in rel):
            raise SandboxError("Path contains control characters.")
        if "\\" in rel:
            raise SandboxError("Use forward slashes in paths.")
        if PurePosixPath(rel).is_absolute() or PureWindowsPath(rel).drive:
            raise SandboxError("Absolute paths are not allowed; use a workspace-relative path.")
        if ":" in rel:
            raise SandboxError("Colons are not allowed in paths.")
        for seg in rel.split("/"):
            if seg in ("", ".", ".."):
                continue
            if seg.endswith((".", " ")):
                raise SandboxError("Path segments cannot end with a dot or a space.")
            if seg.split(".")[0].strip().lower() in _WINDOWS_DEVICE_NAMES:
                raise SandboxError(f"{seg!r} is a reserved device name.")

    @staticmethod
    def _has_protected_part(parts: tuple[str, ...]) -> bool:
        for part in parts:
            low = part.lower()
            if low in PROTECTED_DIRS:
                return True
            if any(fnmatch.fnmatchcase(low, pat) for pat in PROTECTED_NAME_PATTERNS):
                return True
        return False