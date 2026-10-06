# Final Demo Script

Run this from the repository after configuring `.env`, the external workspace,
PM2, and ngrok.

1. Start the service with `pm2 restart mcp-workspace` and confirm `pm2 status`.
2. Open MCP Inspector at `https://<PUBLIC_HOSTNAME>/mcp` using the Reader token.
3. Initialize a session and show the six Reader tools.
4. Call `list_files` on `.` and `read_file` on `PROJECT_STATE.md`.
5. Call `search_files` for `Current Phase` and `git_status` for the workspace.
6. Start a second Inspector connection with the Writer token.
7. Show all ten tools and call `append_state` on `CHECKPOINTS.md`.
8. Call `write_file` on a disposable workspace file, read it back, then call
   `delete_file` and confirm the file moves to `.trash`.
9. Return to the Reader connection and show that writer-only tools are absent.
10. Inspect the JSONL audit log and show that tool names, roles, outcomes, and
    safe summaries were recorded without token values.
11. End by reading `PROJECT_STATE.md` from the second session to demonstrate
    persistent multi-session handoff.

Expected result: Reader can inspect and append handoff state, Writer can modify
workspace content and commit Git changes, and both roles operate on the same
external workspace through the authenticated HTTPS endpoint.
