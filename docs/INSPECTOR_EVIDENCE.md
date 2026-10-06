# MCP Inspector Evidence

Verified during the final deployment session on 2026-10-06:

- MCP Inspector connected through the public HTTPS ngrok endpoint.
- Reader authentication succeeded and exposed exactly six tools:
  `list_files`, `read_file`, `search_files`, `append_state`, `git_status`,
  and `git_diff`.
- Writer authentication succeeded and exposed all ten tools.
- Reader sessions did not receive writer-only operations.
- A Writer workflow read the shared workspace, updated handoff state, and
  exercised the deployed endpoint.
- Handoff state was recovered from a separate MCP session, confirming that the
  external workspace persists across sessions.

The local automated equivalent is covered by `tests/test_streamable_http.py`.
The public endpoint URL is intentionally not stored in this document because
free ngrok hostnames are replaceable; use `PUBLIC_HOSTNAME` from `.env`.
