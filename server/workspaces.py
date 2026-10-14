"""Persistent named workspace registry used by the MCP management tools."""

from __future__ import annotations

import json
import re
from pathlib import Path

from server.sandbox import Sandbox

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$")


class WorkspaceRegistry:
    def __init__(self, path: Path, sandbox: Sandbox) -> None:
        self.path = path
        self.sandbox = sandbox
        self.entries: dict[str, Path] = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict) or not all(
                    isinstance(k, str) and isinstance(v, str)
                    for k, v in raw.items()
                ):
                    raise ValueError
                self.entries = {k: Path(v).resolve() for k, v in raw.items()}
            except (OSError, ValueError, json.JSONDecodeError):
                raise ValueError("Workspace registry is unreadable or invalid.") from None
        else:
            self.entries["default"] = sandbox.root
            self._save()
        if not any(root == sandbox.root for root in self.entries.values()):
            name = "default" if "default" not in self.entries else "configured-root"
            suffix = 2
            while name in self.entries:
                name = f"configured-root-{suffix}"
                suffix += 1
            self.entries[name] = sandbox.root
            self._save()

    @staticmethod
    def _validate_name(name: str) -> str:
        if not isinstance(name, str) or not _NAME.fullmatch(name.strip()):
            raise ValueError("Name must be 1–64 letters, numbers, spaces, dots, underscores, or hyphens.")
        return name.strip()

    def list(self) -> str:
        return "\n".join(
            f"{name}{' (active)' if root == self.sandbox.root else ''}"
            for name, root in sorted(self.entries.items(), key=lambda item: item[0].casefold())
        ) or "No workspaces are registered."

    def register(self, name: str, path: str) -> str:
        name = self._validate_name(name)
        if not isinstance(path, str) or not path.strip():
            raise ValueError("Workspace path must not be empty.")
        try:
            root = Path(path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            raise ValueError("Workspace path does not exist or cannot be resolved.") from None
        if not root.is_dir():
            raise ValueError("Workspace path must be a directory.")
        if name in self.entries and self.entries[name] != root:
            raise ValueError(f"Workspace name {name!r} is already registered.")
        if root in self.entries.values() and self.entries.get(name) != root:
            raise ValueError("That directory is already registered under another name.")
        self.entries[name] = root
        self._save()
        return f"Registered workspace {name!r}."

    def switch(self, name: str) -> str:
        name = self._validate_name(name)
        root = self.entries.get(name)
        if root is None:
            raise ValueError(f"Workspace {name!r} is not registered. Use list_workspaces.")
        try:
            resolved = root.resolve(strict=True)
        except (OSError, RuntimeError):
            raise ValueError(f"Workspace {name!r} is no longer available.") from None
        if not resolved.is_dir():
            raise ValueError(f"Workspace {name!r} is no longer a directory.")
        self.sandbox.root = resolved
        return f"Switched active workspace to {name!r}."

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(
                json.dumps({k: str(v) for k, v in self.entries.items()}, indent=2) + "\n",
                encoding="utf-8",
            )
            temp.replace(self.path)
        except OSError:
            raise ValueError("Cannot save workspace registry.") from None

