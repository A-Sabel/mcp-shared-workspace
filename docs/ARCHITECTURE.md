# Architecture

## Runtime flow

```mermaid
flowchart TD
    Client[MCP client or Inspector] -->|HTTPS /mcp| Ngrok[ngrok tunnel]
    Ngrok --> PM2[PM2 process manager]
    PM2 --> HTTP[server.http_runner]
    HTTP --> Auth[Bearer authentication middleware]
    Auth --> MCP[One MCP server with 10 tools]
    MCP --> Sandbox[Workspace sandbox]
    Sandbox --> Files[Live workspace]
    MCP --> Audit[JSONL audit log]
    MCP --> Git[Workspace Git repository]
```

`server.http_runner` loads settings, builds one MCP server, and serves it under
`/mcp`. `AuthenticationMiddleware` verifies the single bearer token before
forwarding requests. The MCP SDK handles Streamable HTTP sessions; the
application owns path safety, tool registration, and audit records.

## Tool surface

| Authenticated MCP client | Tools                  |
| ------------------------ | ---------------------- |
| `MCP_TOKEN`              | All 10 workspace tools |

The live workspace is external to the server repository. This keeps application
code, credentials, logs, and workspace content separate while allowing the
workspace itself to have its own Git history.
