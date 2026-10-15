# Security And Operational Boundaries

## Controls

- One `MCP_TOKEN` is loaded from the environment and must be a non-placeholder
  value of at least 16 characters.
- The HTTP service supports OAuth authorization-code flow with PKCE and
  dynamic client registration. The sign-in page accepts `MCP_TOKEN` as the
  workspace owner credential; each registered MCP client receives a separate
  short-lived access token and rotating refresh token. OAuth token values are stored as digests
  in `OAUTH_DB_PATH` (default `logs/oauth.sqlite3`).
- Keep the OAuth database private and persistent. Deleting it revokes existing
  OAuth tokens and removes registered clients. Dynamic client registration is
  publicly reachable because OAuth clients need it; registration does not grant
  access until the workspace owner signs in.
- The MCP server publishes the complete toolbox to the authenticated profile.
  OAuth sign-in and the legacy `MCP_TOKEN` authenticate that same profile.
- Authenticated clients can register arbitrary existing directories and switch
  the shared sandbox to them. Treat workspace credentials as trusted with the
  ability to expose and modify those registered projects.
- The workspace registry stores absolute paths in `WORKSPACE_REGISTRY_PATH`
  (default `logs/workspaces.json`); protect it with the same operating-system
  permissions as the server configuration and audit logs.
- Every tool resolves paths relative to `WORKSPACE_ROOT` and rejects traversal,
  absolute paths, control characters, protected names, and symlink escapes.
- `.git`, `.trash`, `.env`, PEM files, and SSH key-like names are protected.
- `delete_file` records a unique trash entry and original-path metadata;
  `restore_file` validates the metadata and refuses destination conflicts.
  `remove_directory` only removes empty directories and never recurses.
- Permanent deletion is not exposed because the current MCP connection has no
  trusted per-call approval channel. A model-provided confirmation parameter
  would not prove that the workspace owner approved the deletion.
- Writes are bounded; state updates are append-only and limited to the four
  handoff files.
- Tool calls are recorded as structured JSONL with redacted argument summaries.
- The supported deployment uses one server process and a workspace directory
  writable only by that server's trusted operating-system identity.
- Transport host and origin checks remain enabled for TestClient and the
  configured public hostname.

## Known limitations

- `read_file` stops after the requested range and one-line lookahead by
  default. It returns `total_lines: null` when it has not reached EOF. Setting
  `count_total_lines=true` scans through EOF to calculate the exact total, even
  when the requested range is near the beginning. This does not send the entire
  file to the model; returned content stays within the tool's response limits.
- The `read_file` response limit is 64 KiB, measured in bytes rather than
  tokens. The actual token cost depends on the returned content and the
  model's tokenizer.
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

Never commit `.env`, tokens, the OAuth database, audit logs, `.trash`, or
Inspector session files.
