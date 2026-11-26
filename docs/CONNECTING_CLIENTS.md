# Connect AI Clients

The server exposes a remote MCP endpoint at:

`https://<PUBLIC_HOSTNAME>/mcp`

Start the MCP server and HTTPS tunnel first. Replace the placeholder with the hostname from your `.env`.

## Codex

Using the CLI:

```powershell
codex mcp add shared-workspace --url https://<PUBLIC_HOSTNAME>/mcp
codex mcp login shared-workspace
codex mcp list
```

Or add this to `%USERPROFILE%\.codex\config.toml`:

```toml
[mcp_servers.shared-workspace]
url = "https://<PUBLIC_HOSTNAME>/mcp"
# For Bearer auth, set MCP_TOKEN in the environment and uncomment:
# bearer_token_env_var = "MCP_TOKEN"
```

In the Codex TUI, use `/mcp` to inspect the connection. See the [Codex MCP guide](https://developers.openai.com/codex/mcp/).

## Claude

Remote custom connectors are supported in Claude, Claude Desktop, and Cowork.

1. Open **Customize → Connectors** (or **Settings → Connectors**, depending on the client).
2. Choose **Add custom connector** and enter a name.
3. Set the server URL to `https://<PUBLIC_HOSTNAME>/mcp`.
4. Complete the detected OAuth sign-in flow.

For plans or clients that offer request-header authentication instead, use a Bearer authorization header with your `MCP_TOKEN`. Do not paste the token into a shared document.

See [Claude remote MCP connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).

## ChatGPT

Custom remote MCP connections are available only on supported ChatGPT plans and workspaces; availability and admin permissions vary.

1. Open **Plugins** and choose **Add custom MCP server**.
2. Enter a name and `https://<PUBLIC_HOSTNAME>/mcp` as the server URL.
3. Configure authentication as prompted and complete the connection.
4. Review the discovered tools before using the connection.

If the custom MCP option is not available in your workspace, your plan or administrator may not permit it. See [Connecting custom MCP servers in ChatGPT](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt).

## Other MCP Clients

For clients that support remote MCP over **Streamable HTTP**:

1. Add a remote HTTP/Streamable HTTP MCP server.
2. Set its URL to `https://<PUBLIC_HOSTNAME>/mcp`.
3. Choose OAuth if supported and complete sign-in.
4. Otherwise, configure an `Authorization: Bearer <token>` header using a securely stored `MCP_TOKEN`, if the client supports custom headers.

Client configuration screens and authentication support differ. Check the client's MCP documentation if it does not support OAuth or custom headers.

## First Task Prompt

After connecting, try this prompt in your AI client:

```text
Read AGENTS.md and PROJECT_STATE.md if present. Check the project structure and Git status,
then identify the relevant files before editing. Use targeted reads and the expected_hash
from read_file when editing. Run relevant tests and summarize changes and results.
Do not commit or push unless I ask.
```

## Troubleshooting

- **Connection refused or timeout:** confirm the server and HTTPS tunnel are running.
- **401 Unauthorized:** complete OAuth sign-in again, or verify the Bearer token configuration.
- **Tools missing:** reconnect or refresh the client's MCP tool list.
- **Wrong project:** check the active workspace in the MCP server.

## Security

The endpoint exposes workspace tools over the internet. Connect only clients you trust, keep `MCP_TOKEN` secret, and do not put credentials in prompts, source control, or shared configuration files.
