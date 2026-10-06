# DECISIONS

Append one entry per decision: choice, reason, alternatives rejected.

### 2026-10-07 UTC

- Keep the live workspace outside the server repository so workspace Git state,
  application code, credentials, and audit logs remain separate.
- Use two role-specific MCP server instances behind authentication middleware;
  this makes the Reader/Writer tool boundary explicit instead of relying only
  on tool-call checks.
- Configure the public hostname with `PUBLIC_HOSTNAME`; do not hard-code a free
  ngrok hostname because it can change between sessions.
- Leave symlink security logic unchanged and document the seven skipped Windows
  tests rather than weakening the path controls to accommodate the environment.
- Keep `.env`, audit logs, `.trash`, and Inspector session artifacts out of Git.
