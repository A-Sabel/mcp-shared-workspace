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
pm2 start ecosystem.config.cjs
pm2 save
pm2 status
```

`ecosystem.config.cjs` uses `.venv\Scripts\python.exe -m server.http_runner`,
which binds the MCP server to `127.0.0.1:8000`. PM2 restarts the process after
failure. After changing the ngrok hostname, update `PUBLIC_HOSTNAME` and run:

```powershell
pm2 restart mcp-workspace
```

## Recovery checks

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing
pm2 logs mcp-workspace --lines 50
```

The health path requires authentication and should return `401` without a
Bearer token. Use the MCP Inspector against `https://<PUBLIC_HOSTNAME>/mcp`
with the configured `MCP_TOKEN`; the connection should expose all ten tools.

## Stop

```powershell
pm2 stop mcp-workspace
pm2 delete mcp-workspace
```
