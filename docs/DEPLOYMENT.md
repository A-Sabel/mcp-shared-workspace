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
server process to `127.0.0.1:8000`. PM2 restarts the process after failure.
You can also launch it hidden with `deployment\windows\start-mcp-hidden.vbs`.
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
`MCP_TOKEN`; initialization should succeed and expose all ten tools. Supply the
token through Inspector's secret/header UI, not a URL or saved command.

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
