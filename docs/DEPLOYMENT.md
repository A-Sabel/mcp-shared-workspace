# Deployment: PM2 And ngrok

## Configure

1. Create the external workspace and seed it from `examples/workspace`.
2. Copy `.env.example` to `.env`.
3. Set `WORKSPACE_ROOT`, one `MCP_TOKEN`, and `PUBLIC_HOSTNAME` to the ngrok
   hostname only, for example
   `example.ngrok-free.dev`.
4. Keep `.env` local; it is ignored by Git.

## Start

From the repository directory:

```powershell
ngrok http 8000
pm2 start deployment\windows\ecosystem.config.cjs
pm2 save
pm2 status
```

`deployment\windows\ecosystem.config.cjs` resolves the repository root and
uses `.venv\Scripts\python.exe -m server.http_runner`, which binds one MCP
server process to `127.0.0.1:8000`. PM2 can supervise this process for manual
terminal-based operation.
For one-click control, double-click `deployment\windows\start-workspace-hidden.vbs`.
It opens a Windows control app with **Start**, **Pause**, and **Exit**. Start
runs the MCP service and ngrok as hidden child processes without terminal
windows. Before starting, it removes the previous `mcp-workspace` PM2 entry.
Pause stops the public tunnel and MCP service while leaving the control app open. Exit, or
the window close button, stops both and closes the app. The app shows the MCP
endpoint and activity; startup messages are recorded in `logs/launcher.log`
and Python output in `logs/mcp-server.log`. The computer must remain awake and online while Claude
needs access. The standalone PM2 launcher remains available at
`deployment\windows\start-mcp-hidden.vbs`. From PowerShell, run the combined
launcher with the windowless Windows Script Host explicitly:

```powershell
wscript.exe .\deployment\windows\start-workspace-hidden.vbs
```

Open the VBS launcher from File Explorer or its desktop shortcut. PM2
application output is available with `pm2 logs mcp-workspace`.
Keep the external workspace writable only by the
operating-system identity that runs this service. Do not run a second server
process against the same audit log. After changing the ngrok hostname, update
`PUBLIC_HOSTNAME` and run:

```powershell
pm2 restart mcp-workspace
```

## Recovery checks

An unauthenticated probe should return `401`; that confirms the HTTP process is
responding without exposing the token:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing
pm2 logs mcp-workspace --lines 50
```

For an authenticated health check, prompt for the token so it is not stored in
the command text or shell history:

```powershell
$credential = Get-Credential -UserName 'mcp' -Message 'Enter MCP_TOKEN'
$token = $credential.GetNetworkCredential().Password
try {
    Invoke-WebRequest http://127.0.0.1:8000/health -Headers @{ Authorization = "Bearer $token" } -UseBasicParsing
} finally {
    $token = $null
    $credential = $null
}
```

After a hostname change, verify the unauthenticated health response, then use
MCP Inspector against `https://<PUBLIC_HOSTNAME>/mcp` with the configured
`MCP_TOKEN`; initialization should succeed and expose the workspace tools. At
this Inspector flow, the legacy `MCP_TOKEN` grants the same workspace access.
Supply it through Inspector's secret/header UI, not a URL or saved command.
For Claude's OAuth sign-in flow below, enter the workspace access key to
authorize the profile.

## Connect Claude using OAuth

The HTTP server publishes OAuth metadata and a protected-resource document.
In Claude, add a custom connector using `https://<PUBLIC_HOSTNAME>/mcp` and
choose **Sign in now**, then choose **Register automatically** for the OAuth
client. Claude should open the workspace sign-in page. Enter the configured
`MCP_TOKEN` as the workspace access key to authorize it. The
server then issues Claude its own expiring OAuth tokens. Keep the ngrok tunnel
running, and keep `logs/oauth.sqlite3` private and persistent; deleting that
database removes OAuth registrations and revokes issued sessions. If the
hostname changes, update `PUBLIC_HOSTNAME`, restart PM2, then update the
connector URL and sign in again.

## Audit log operations

The service writes `LOG_PATH` as JSONL. It rotates the active file at 10 MiB,
keeps five numbered backups, and removes the oldest backup on the next
rotation. The PM2 configuration runs one server process; this process-local
rotation and lock do not support multiple workers writing the same log. Keep
the log directory writable only by the service identity and include it in
host-level backup/retention policy if records must be retained longer.

Audit writes are synchronous and fail closed: if the log directory or disk is
unwritable/full, a tool call may fail. Check free disk space and directory
permissions, restore writable space, then retry. Do not delete active logs
while the service is running; copy them elsewhere before archival or cleanup.

## Stop

```powershell
pm2 stop mcp-workspace
pm2 delete mcp-workspace
```
