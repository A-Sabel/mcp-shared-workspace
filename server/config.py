"""Settings and output limits. Secrets come from the environment / .env."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Repository root, so .env and relative paths work from any working directory
# (important when a process manager starts the server from somewhere else).
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Limits that keep tool results small (token efficiency).
MAX_READ_LINES = 200          # per range in read_file
MAX_READ_RANGES = 5           # ranges per read_file call
LIST_LIMIT = 200              # entries per list_files call
SEARCH_LIMIT = 50             # matches per search_files call
SNIPPET_CHARS = 120           # trimmed match line in search_files
MAX_WRITE_BYTES = 1_000_000   # write_file / append_state size cap
MAX_GIT_OUTPUT_CHARS = 20_000  # git_diff / git_status cap

MIN_TOKEN_LEN = 16


class ConfigError(RuntimeError):
    """Startup configuration is missing or unsafe."""


@dataclass(frozen=True)
class Settings:
    workspace_root: Path
    reader_token: str
    writer_token: str
    log_path: Path


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read settings from `env` (defaults to os.environ after loading .env)."""
    if env is None:
        load_dotenv(PROJECT_ROOT / ".env")
        env = os.environ

    root_raw = env.get("WORKSPACE_ROOT", "").strip()
    if not root_raw:
        raise ConfigError("WORKSPACE_ROOT is not set.")
    root = Path(root_raw).expanduser().resolve()
    if not root.is_dir():
        raise ConfigError("WORKSPACE_ROOT does not exist or is not a directory.")

    reader = env.get("READER_TOKEN", "").strip()
    writer = env.get("WRITER_TOKEN", "").strip()
    for name, token in (("READER_TOKEN", reader), ("WRITER_TOKEN", writer)):
        if not token:
            raise ConfigError(f"{name} is not set.")
        if len(token) < MIN_TOKEN_LEN or token.lower().startswith("change-me"):
            raise ConfigError(f"{name} is a placeholder or too short (min {MIN_TOKEN_LEN} chars).")
    if reader == writer:
        raise ConfigError("READER_TOKEN and WRITER_TOKEN must differ.")

    log_path = Path(env.get("LOG_PATH", "logs/tool_calls.jsonl")).expanduser()
    if not log_path.is_absolute():
        log_path = PROJECT_ROOT / log_path

    return Settings(root, reader, writer, log_path.resolve())