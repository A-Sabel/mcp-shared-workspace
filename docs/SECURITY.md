# Security And Operational Boundaries

## Controls

- Bearer tokens are loaded from environment variables and must be distinct,
  non-placeholder values of at least 16 characters.
- Reader and writer requests are routed to separate MCP server instances.
- Every tool resolves paths relative to `WORKSPACE_ROOT` and rejects traversal,
  absolute paths, control characters, protected names, and symlink escapes.
- `.git`, `.trash`, `.env`, PEM files, and SSH key-like names are protected.
- Writes are bounded; state updates are append-only and limited to the four
  handoff files.
- Tool calls are recorded as structured JSONL with redacted argument summaries.
- Transport host and origin checks remain enabled for TestClient and the
  configured public hostname.

## Known limitations

- A hard link inside the workspace can refer to an outside inode and cannot be
  identified using path checks alone.
- A symlink can be swapped between validation and the file operation (TOCTOU).
  The workspace must be writable only by trusted processes.
- Seven symlink-focused tests are skipped on the current Windows environment
  because symlink creation is unavailable. Run the suite on a symlink-capable
  system for full coverage; the production security logic is unchanged.
- Free ngrok hostnames can change. Set `PUBLIC_HOSTNAME` and restart PM2 when
  the tunnel hostname changes.

Never commit `.env`, tokens, audit logs, `.trash`, or Inspector session files.
