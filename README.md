# MCP Shared Workspace Server

A sandboxed Python MCP server exposes a persistent shared
workspace over Streamable HTTP. It provides one authenticated 15-tool toolbox,
append-only handoff files, audit logging, and Git operations.

## Capabilities

The configured `MCP_TOKEN` is the workspace owner credential. OAuth sign-in
authenticates that same profile and grants access to all workspace tools. The
server enforces authentication and sandbox checks on every operation.

Every filesystem path passes through the sandbox. Protected names, traversal,
symlink escapes, oversized reads/writes, and unsafe Git arguments are rejected.
The known hard-link and TOCTOU limitations are recorded in [docs/SECURITY.md](docs/SECURITY.md).

## Tools

The MCP server exposes 15 tools to the authenticated workspace profile.

| Tool                 | What it can do                                                  |
| -------------------- | --------------------------------------------------------------- |
| `list_files`         | Browse files and folders in the workspace.                      |
| `read_file`          | Read bounded chunks with line counts and continuation metadata. |
| `search_files`       | Search workspace files by text or regular expression.           |
| `append_state`       | Add a handoff entry to the shared state files.                  |
| `git_status`         | Show the workspace Git status.                                  |
| `git_diff`           | Inspect bounded unstaged Git changes.                           |
| `write_file`         | Create or replace a workspace text file.                        |
| `str_replace`        | Make an exact, targeted text replacement.                       |
| `delete_file`        | Soft-delete a file by moving it to `.trash`.                    |
| `restore_file`       | Restore a soft-deleted file without overwriting conflicts.      |
| `remove_directory`   | Remove an empty directory; non-empty directories are refused.   |
| `git_commit`         | Commit explicitly selected safe workspace paths.                |
| `list_workspaces`    | List registered project workspaces and the active one.          |
| `register_workspace` | Register an existing project directory by name.                 |
| `switch_workspace`   | Make a registered project the active workspace.                 |

The AI chooses the tools needed for each task. The server still validates every
request before it reaches the workspace.

For complete-file requests, `read_file` reports `total_lines`, `has_more`, and
`next_start_line`. Continue from that line until `has_more` is false. Reads are
limited to 200 lines per chunk and 64 KiB per response; unusually long lines
that cannot fit in a response are reported as an error.

## Measure Tool And Token Efficiency

Successful tool calls add content-free output byte and character counts to the
JSONL audit log. `read_file` calls also record line-range and continuation
metadata. The telemetry excludes returned file contents and measures server
output size, not model token usage. For a paired baseline/candidate evaluation
using actual client token counts and task pass/completeness ratings, follow
[benchmarks/README.md](benchmarks/README.md). The scripts under `scripts/`
summarize audit telemetry and benchmark results.

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

Seed and initialize the external workspace:

```powershell
New-Item -ItemType Directory ..\mcp-workspace -Force
Copy-Item examples\workspace\* ..\mcp-workspace -Recurse -Force
Set-Location ..\mcp-workspace
git init
git add -A
git commit -m "chore: seed workspace"
```

Start a local HTTP instance and run the tests:

```powershell
python -m server.http_runner
python -m pytest -q
```

The authenticated MCP endpoint is `http://127.0.0.1:8000/mcp`. It exposes
all 15 tools to authenticated clients. The server remains responsible for
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
tool audit counts and read coverage, plus any paired token benchmark results
entered in `benchmarks/results.csv`. The registry is stored in
`logs/workspaces.json`.

For quicker startup, create a Windows shortcut that runs
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<repo>\deployment\windows\workspace-control.ps1"`
and pin it to your desktop or taskbar.

Permanent deletion is not exposed until a trusted approval flow is available.
`delete_file` moves files into uniquely named `.trash` entries with metadata;
use the returned `trash_path` with `restore_file`. `remove_directory` only
removes empty directories.

Set `PUBLIC_HOSTNAME` to the hostname reported by ngrok, then restart after
configuration changes:

```powershell
pm2 restart mcp-workspace
```

Connect an MCP client or Inspector to
`https://<PUBLIC_HOSTNAME>/mcp` with `Authorization: Bearer MCP_TOKEN`.
The authenticated session should initialize successfully and list exactly 10
tools. Keep `.env`, tokens, logs, and the external workspace out of commits.

## Run And Test

```powershell
python -m server.http_runner
python -m pytest
```

For PM2 and ngrok, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). The repeatable
acceptance flow is in [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

## Project Map

```text
.github/             CI and dependency update automation
server/              MCP app, core sandbox/audit, tools, and security modules
tests/               Unit, security, HTTP, and MCP integration tests
docs/                Architecture, security, operations, demo, and tracking
benchmarks/          Repeatable token-efficiency tasks and results template
scripts/             Audit telemetry and benchmark reporting
deployment/windows/  PM2 configuration and hidden Windows launcher
examples/workspace/  Seed handoff files for the external workspace
requirements/        Runtime, locked, and development dependency manifests
README.md            Setup, capabilities, and project entry points
```

The stdio development entry point is `python -m server.main`.
