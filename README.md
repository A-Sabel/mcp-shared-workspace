# MCP Shared Workspace Server

A sandboxed Python MCP server exposes a persistent shared
workspace over Streamable HTTP. It provides one authenticated 10-tool toolbox,
append-only handoff files, audit logging, and Git operations.

## Capabilities

The configured `MCP_TOKEN` authenticates the MCP client, which receives all ten
tools. The AI chooses the minimum necessary tool for each task; the server
remains authoritative for sandbox validation and safety checks.

Every filesystem path passes through the sandbox. Protected names, traversal,
symlink escapes, oversized reads/writes, and unsafe Git arguments are rejected.
The known hard-link and TOCTOU limitations are recorded in [docs/SECURITY.md](docs/SECURITY.md).

## Tools

The authenticated MCP client can use all 10 tools:

| Tool           | What it can do                                        |
| -------------- | ----------------------------------------------------- |
| `list_files`   | Browse files and folders in the workspace.            |
| `read_file`    | Read selected line ranges from text files.            |
| `search_files` | Search workspace files by text or regular expression. |
| `append_state` | Add a handoff entry to the shared state files.        |
| `git_status`   | Show the workspace Git status.                        |
| `git_diff`     | Inspect bounded unstaged Git changes.                 |
| `write_file`   | Create or replace a workspace text file.              |
| `str_replace`  | Make an exact, targeted text replacement.             |
| `delete_file`  | Soft-delete a file by moving it to `.trash`.          |
| `git_commit`   | Commit explicitly selected safe workspace paths.      |

The AI chooses the tools needed for each task. The server still validates every
request before it reaches the workspace.

## Setup And Replication

Requires Python 3.10+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-lock.txt
Copy-Item .env.example .env
```

Configure `.env` with:

- `WORKSPACE_ROOT`: an external directory containing the shared workspace.
- `MCP_TOKEN`: a generated random Bearer token.
- `PUBLIC_HOSTNAME`: the ngrok hostname without `https://` when using HTTPS.

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
all 10 tools to the authenticated client. The server remains responsible for
path validation, protected files, write limits, Git safety, soft-delete, and
audit logging.

To replicate the public deployment with PM2 and ngrok:

```powershell
ngrok http 8000
pm2 start ecosystem.config.cjs
pm2 save
pm2 status
```

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
server/             MCP server, sandbox, tools, auth, audit, HTTP entry point
examples/workspace/ Seed handoff files
tests/              unit, security, HTTP, and MCP integration tests
docs/               architecture, security, deployment, evidence, demo
logs/               local audit output; ignored by Git
```

The stdio development entry point is `python -m server.main`.
