# Security And Operational Boundaries

## Controls

- One `MCP_TOKEN` is loaded from the environment and must be a non-placeholder
  value of at least 16 characters.
- The authenticated client receives the complete MCP toolbox; tool choice is
  an agent-planning concern, not an authorization mechanism.
- Every tool resolves paths relative to `WORKSPACE_ROOT` and rejects traversal,
  absolute paths, control characters, protected names, and symlink escapes.
- `.git`, `.trash`, `.env`, PEM files, and SSH key-like names are protected.
- Writes are bounded; state updates are append-only and limited to the four
  handoff files.
- Tool calls are recorded as structured JSONL with redacted argument summaries.
- The supported deployment uses one server process and a workspace directory
  writable only by that server's trusted operating-system identity.
- Transport host and origin checks remain enabled for TestClient and the
  configured public hostname.

## Known limitations

- A hard link inside the workspace can refer to an outside inode and cannot be
  identified using path checks alone.
- A symlink can be swapped between validation and the file operation (TOCTOU).
  Path checks do not make operations safe against a hostile concurrent writer.
  Do not grant write access to `WORKSPACE_ROOT` to other operating-system
  accounts or untrusted services. On Windows, configure and review the
  directory ACL for the PM2 account; on POSIX, use a dedicated service account
  and restrictive ownership and permissions. Processes running as an
  authorized account are trusted by this deployment model. This boundary does
  not make the file operations race-resistant if that account or process is
  compromised.
- Windows may skip symlink-focused tests when the runner lacks symlink
  privileges. The Linux CI job is intended to run the symlink cases.
- Free ngrok hostnames can change. Set `PUBLIC_HOSTNAME` and restart PM2 when
  the tunnel hostname changes.

Never commit `.env`, tokens, audit logs, `.trash`, or Inspector session files.
