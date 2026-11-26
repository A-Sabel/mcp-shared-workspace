# MCP Shared Workspace Server

A sandboxed Python MCP server exposes a persistent shared
workspace over Streamable HTTP. It provides one authenticated toolbox,
shared state management, audit logging, compact project context, source outlines,
and Git operations.

## Use it as a coding agent from any MCP client

No Claude Code or Codex subscription? Connect this server to an MCP-capable
assistant and it can browse, search, edit, patch, test and commit in your project.
Tested with Codex. Claude also supports remote custom connectors, including one on
the free plan.

1. Start the server and tunnel (see Setup) and note your public `https://<host>/mcp` URL.
2. Connect your client and authenticate with OAuth or your `MCP_TOKEN` as a Bearer token:
   - **Claude:** Connectors → Add custom connector → paste the URL.
   - **Codex:** add it as a remote HTTP server in your Codex MCP config.
3. Start a chat or session and ask: "Read AGENTS.md, then `<task>`".

Limits: free chat plans have message limits, and Claude's free plan allows one
custom connector. Your PC and the tunnel must be running. It works on projects
stored on the machine running the server; there are no push, pull or clone tools.
There is no arbitrary shell access: only allowlisted pytest/ruff/mypy checks run.
It works while the session is open; it is not a background agent.

Security: this exposes your project over a public URL. Keep `MCP_TOKEN` secret and
rotate it if it leaks.

## Capabilities

The configured `MCP_TOKEN` is the workspace owner credential. OAuth sign-in
authenticates that same profile and grants access to all workspace tools. The
server enforces authentication and sandbox checks on every operation.

Every filesystem path passes through the sandbox. Protected names, traversal,
symlink escapes, over-limit writes, and unsafe Git arguments are rejected.
File reads are capped per chunk and by response size, with continuation metadata
for the remaining content.
The known hard-link and TOCTOU limitations are recorded in [docs/SECURITY.md](docs/SECURITY.md).

## Tools

The MCP server exposes the tools registered by the server modules to the authenticated workspace profile.

| Tool                 | What it can do                                                  |
| -------------------- | --------------------------------------------------------------- |
| `list_files`         | Browse files and folders; sizes and line counts are opt-in.     |
| `read_file`          | Read bounded chunks; optionally count all file lines.            |
| `search_files`       | Search workspace files by text or regular expression.           |
| `append_state`       | Add a handoff entry to the shared state files.                  |
| `git_status`         | Show the workspace Git status.                                  |
| `git_diff`           | Inspect bounded staged, unstaged, or combined Git changes.       |
| `write_file`         | Create or replace a file, optionally guarded by SHA-256 or create-only mode. |
| `str_replace`        | Replace exact text, optionally guarded by its SHA-256 hash.      |
| `delete_file`        | Soft-delete a file by moving it to `.trash`.                    |
| `list_trash`         | Browse soft-deleted files and recover their exact restore paths. |
| `restore_file`       | Restore a soft-deleted file without overwriting conflicts.      |
| `remove_directory`   | Remove an empty directory; non-empty directories are refused.   |
| `move_file`           | Move or rename a regular file within the workspace.               |
| `create_directory`    | Create a directory and any missing parent directories.            |
| `read_state`          | Read bounded recent entries or a selected state section.           |
| `archive_state`       | Preserve a state file as an immutable archive copy.                 |
| `compact_state`       | Archive full state before applying an agent-provided summary.       |
| `read_audit_log`      | Read bounded, filtered recent audit records.                        |
| `apply_patch`         | Apply exact-context patches with staged replacements and rollback on swap failures. |
| `find_symbol`         | Find likely declarations of a symbol across source files.         |
| `find_references`     | Find lexical references to a symbol across source files.          |
| `git_list_branches`   | List local branches and identify the current branch.              |
| `git_create_branch`   | Create a local branch without switching or overwriting.           |
| `git_switch_branch`   | Switch to an existing branch only from a clean working tree.      |
| `git_unstage`         | Unstage only explicitly selected paths without changing working files. |
| `git_restore`         | Preview or restore explicitly selected working-tree paths; confirmation required. |
| `git_stash`           | List, push, apply, pop, or confirmed drop of Git stashes.           |
| `git_commit`         | Commit explicitly selected safe workspace paths.                |
| `git_log`            | Show recent commits and changed-file summaries.                  |
| `get_workspace_context` | Return selected project context within a token budget.         |
| `get_file_outline`   | Extract imports and declarations from source files.              |
| `get_project_map`    | Map modules, imports, entry points, and root configuration.      |
| `get_change_impact`  | Estimate dependencies, references, and tests affected by a change. |
| `run_project_checks` | Run allowlisted, configured pytest, Ruff, or mypy checks.         |
| `delete_workspace`   | Unregister a workspace without deleting its project files.        |
| `list_workspaces`    | List registered project workspaces and the active one.          |
| `register_workspace` | Register an existing project directory by name.                 |
| `switch_workspace`   | Make a registered project the active workspace.                 |

The AI chooses the tools needed for each task. The server still validates every
request before it reaches the workspace.

State tools are restricted to the four approved handoff files. `read_state` returns
recent timestamped entries by default, with bounded entry counts, or an exact
second-level Markdown section. `archive_state` preserves the current file without
changing it. `compact_state` first creates a content-addressed archive, then atomically
replaces the active file with the agent-supplied summary; the server does not generate
summaries or delete archived history. Archives are stored under `.workspace-archive/`.
Branch tools operate on local branches only. `git_create_branch` validates the ref and refuses an existing name without changing the current branch. `git_switch_branch` refuses any staged, unstaged, or untracked changes. `git_unstage` changes only the index for explicit paths. `git_restore` previews by default and requires `confirm=true` plus explicit paths before discarding working-tree changes. `git_stash` supports list/push/apply/pop/drop; untracked files are included only with `include_untracked=true`, stash drops require confirmation, and `pop` applies before dropping so conflicts retain the stash.

`run_project_checks` optionally reads `.mcp-workspace-checks.json`, whose only supported keys are `pytest`, `ruff`, and `mypy`, each with a `paths` array. The file can select existing workspace-relative targets but cannot provide commands, flags, environment variables, or executable scripts; the server constructs every command from its fixed allowlist. Without this file, the prior automatic configuration detection and default pytest behavior remain.

`find_symbol` uses Python AST for Python declarations and conservative declaration patterns for other supported source types. `find_references` performs bounded lexical matching; it is not a language-server-grade semantic index. Both report partial results when the file scan limit is reached.

`apply_patch` accepts unified diffs for existing UTF-8 files only. It validates every target and exact hunk context before writing, rejects renames/creation/deletion and protected paths, and stages both replacement contents and rollback copies before swapping. If a swap fails, it attempts to restore every original file; this provides rollback for ordinary runtime failures, not crash-safe filesystem-wide atomicity. It does not support fuzzy matching. Pass `expected_hash` for a single-file patch, or an `expected_hashes` mapping covering every patched path, to reject stale edits.
`read_audit_log` reads at most the last 1 MB of JSONL data and returns at most 200
matching records / 64 KB. `move_file` refuses overwrites unless explicitly enabled.

`read_file` returns `total_lines`, `has_more`, and `next_start_line` so the AI can
decide whether it has enough information for the task. If it needs more, it can
request the next chunk from `next_start_line`, or batch up to five known-needed
chunks with `ranges`. For complete-file requests, it should continue until
`has_more` is false. By default, targeted reads stop after the requested range
and one-line lookahead; `total_lines` is omitted when EOF was not reached. Set
`count_total_lines=true` to scan through EOF for an exact total. Each call is
limited to 200 lines per range and 64 KiB; an unusually long line that cannot
fit in a response is an error.

`get_change_impact` accepts a workspace-relative file path or a symbol name. It reports likely importers, text references, and related tests using static analysis; treat the results as leads to verify, not a complete runtime dependency graph.

`git_diff` accepts `mode=unstaged` (default), `mode=staged`, or `mode=both`.
For concurrent edits, pass the `sha256` returned by `read_file` as `expected_hash`
to `write_file`, `str_replace`, or a single-file `apply_patch`. For multi-file patches,
pass `expected_hashes` with an entry for every patched path. A mismatch returns a conflict
and leaves the patch unapplied; conflict errors include the current file hash for re-reading and merging. `write_file` also supports `create_only=true` to refuse
existing targets. These checks use a shared process-local lock and do not provide cross-process
compare-and-swap guarantees. `list_files` and `search_files` return deterministically ordered results within their bounded scans; pagination is offset-based only where exposed, so concurrent file changes can shift later pages.
respect Git ignore rules when run inside a Git repository with Git available;
when Git cannot be used, they fall back to normal sandboxed traversal.

## Measure Tool And Token Efficiency

Successful tool calls add content-free output byte and character counts to the
JSONL audit log. `read_file` calls also record line-range and continuation
metadata. The telemetry excludes returned file contents and measures server
output size, not model token usage. `scripts/report_tool_usage.py` summarizes
audit telemetry. `scripts/summarize_token_benchmark.py` summarizes a paired
baseline/candidate CSV when you provide actual client token counts and
task pass/completeness ratings; benchmark data is local and git-ignored.

## Setup And Replication

Requires Python 3.10+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements/requirements-lock.txt
Copy-Item .env.example .env
```

Configure `.env` with:

- `WORKSPACE_ROOT`: an external directory containing the shared workspace.
- `MCP_TOKEN`: a generated random Bearer token.
- `PUBLIC_HOSTNAME`: the ngrok hostname without `https://` when using HTTPS.
- `WORKSPACE_REGISTRY_PATH` (optional): registry file path; defaults to `logs/workspaces.json`.

Generate a token with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Create and initialize the external workspace. Copy or create your project files
in this directory before connecting clients:

```powershell
New-Item -ItemType Directory ..\mcp-workspace -Force
Push-Location ..\mcp-workspace
git init
Pop-Location
```

Start the local HTTP server in one terminal:

```powershell
python -m server.http_runner
```

Run the automated test suite in another terminal:

```powershell
python -m pytest -q
```

The authenticated MCP endpoint is `http://127.0.0.1:8000/mcp`. It exposes
all registered tools to authenticated clients. The server remains responsible for
path validation, protected files, write limits, Git safety, soft-delete, and
audit logging.

The Windows PM2 configuration and hidden launcher are grouped in
`deployment/windows/`. To replicate the public deployment with PM2 and ngrok:

```powershell
ngrok http 8000
pm2 start deployment\windows\ecosystem.config.cjs
pm2 save
pm2 status
```

The Windows workspace control app provides a project selector and folder
registration form on its **Workspace** tab. Choose a registered project and
press **Switch workspace**; if the service is running, the app restarts the MCP
server and tunnel with that project selected. The **Usage** tab summarizes
tool audit counts and read coverage, plus optional paired token benchmark
results entered in the local, git-ignored `benchmarks/results.csv`. The
registry is stored in `logs/workspaces.json`.

Use **Reload server** in the control app after finishing server edits. The
button restarts the MCP worker on demand, so saving files does not interrupt
connected clients mid-edit. New `server/tools/*_tools.py` modules with a
`register(mcp, sandbox, log_path=...)` function are discovered automatically
at startup, without a manual import or registration edit in `server/main.py`.
Reloading briefly interrupts MCP sessions; clients that do not reconnect and
refresh their tool list automatically may need to reconnect once.

For quicker startup, create a Windows shortcut that runs
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<repo>\deployment\windows\workspace-control.ps1"`
and pin it to your desktop or taskbar.

Permanent deletion is not exposed until a trusted approval flow is available.
`delete_file` moves files into uniquely named `.trash` entries with metadata;
use the returned `trash_path` with `restore_file`, or recover it later through
`list_trash` (bounded with `limit` and `offset`). `remove_directory` only removes
empty directories.

Set `PUBLIC_HOSTNAME` to the hostname reported by ngrok, then restart after
configuration changes:

```powershell
pm2 restart mcp-workspace
```

Connect an MCP client or Inspector to `https://<PUBLIC_HOSTNAME>/mcp`. OAuth
clients can sign in with the workspace access key; legacy clients can use
`Authorization: Bearer MCP_TOKEN`. An authenticated session exposes the
server's current tool catalog. Keep `.env`, tokens, logs, and the external
workspace out of commits.

## Run And Test

Start the server:

```powershell
python -m server.http_runner
```

In a separate terminal, run tests:

```powershell
python -m pytest
```

For PM2 and ngrok, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). The automated
acceptance checks are in `tests/`.

## Project Map

```text
.github/             CI and dependency update automation
server/              MCP app, core sandbox/audit, tools, and security modules
tests/               Unit, security, HTTP, and MCP integration tests
docs/                Architecture, security, deployment, and Inspector notes
scripts/             Audit telemetry and optional benchmark CSV reporting
deployment/windows/  PM2 configuration and hidden Windows launcher
requirements/        Runtime, locked, and development dependency manifests
README.md            Setup, capabilities, and project entry points
```

The stdio development entry point is `python -m server.main`.
