# MCP Shared Workspace Server

A sandboxed Python MCP server exposes a persistent shared
workspace over Streamable HTTP. It provides 10 tools, reader/writer roles,
append-only handoff files, audit logging, and Git operations.

## Capabilities

Reader tokens expose `list_files`, `read_file`, `search_files`, `append_state`,
`git_status`, and `git_diff`. Writer tokens additionally expose `write_file`,
`str_replace`, `delete_file`, and `git_commit`.

Every filesystem path passes through the sandbox. Protected names, traversal,
symlink escapes, oversized reads/writes, and unsafe Git arguments are rejected.
The known hard-link and TOCTOU limitations are recorded in [docs/SECURITY.md](docs/SECURITY.md).

## Setup

Requires Python 3.10+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-lock.txt
Copy-Item .env.example .env
```

Set `WORKSPACE_ROOT` to a separate directory containing the shared handoff
files, generate distinct random `READER_TOKEN` and `WRITER_TOKEN` values, and
set `PUBLIC_HOSTNAME` to the ngrok hostname without `https://`.

To seed a workspace:

```powershell
New-Item -ItemType Directory ..\mcp-workspace -Force
Copy-Item examples\workspace\* ..\mcp-workspace -Recurse -Force
Set-Location ..\mcp-workspace
git init
git add -A
git commit -m "chore: seed workspace"
```

## Run And Test

```powershell
python -m server.http_runner
python -m pytest
```

For PM2 and ngrok, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). The repeatable
acceptance flow is in [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

## Project Map

```text
server/             MCP server, sandbox, tools, auth, audit, HTTP entry point
examples/workspace/ Seed handoff files
tests/              unit, security, HTTP, and MCP integration tests
docs/               architecture, security, deployment, evidence, demo
logs/               local audit output; ignored by Git
```

The stdio development entry point is `python -m server.main --role reader`.
