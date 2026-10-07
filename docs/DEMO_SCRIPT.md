# Final Demo Script

Run this from the repository after configuring `.env`, the external workspace,
PM2, and ngrok.

1. Start the service with `pm2 restart mcp-workspace` and confirm `pm2 status`.
2. Open MCP Inspector at `https://<PUBLIC_HOSTNAME>/mcp` using the configured
   `MCP_TOKEN`.
3. Initialize a session and show all ten tools.
4. Call `list_files` on `.` and `read_file` on `PROJECT_STATE.md`.
5. Call `search_files` for `Current Phase` and `git_status` for the workspace.
6. Call `append_state` on `CHECKPOINTS.md`.
7. Call `write_file` on a disposable workspace file, read it back, then call
   `delete_file` and confirm the file moves to `.trash`.
8. Inspect the JSONL audit log and show that tool names, client, outcomes, and
   safe summaries were recorded without token values.
9. End by reading `PROJECT_STATE.md` from the same session to demonstrate
   persistent multi-session handoff.

Expected result: one authenticated client can inspect, update, and commit the
same external workspace through the HTTPS endpoint, while the server remains
the final authority over sandbox safety.
