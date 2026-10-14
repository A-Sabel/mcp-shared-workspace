# MCP Status and Testing

Date: 2026-10-14
Server: MCP Shared Workspace

## Latest Reported Checks

| Area | Result |
| --- | --- |
| Whole-workspace `search_files` | Passed for root-level `hello_world.py` and `MCP_STATUS.md`. |
| `search_files` filename globs | Passed for exact filename, `*.ini`, and `*.py`; root files are included. |
| No-match glob | Returns a clear “No files matched glob” message. |
| `append_state` | Passed; timestamped entry appended without losing existing content. |
| `write_file`, `read_file`, `delete_file`, `git_status` | Passed in the reported checks. |
| `restore_file` on connected server | Still absent from the advertised tool list. |

The local source registers `restore_file` in `server/tools/write_tools.py`; a
local MCP tool-list inspection confirmed that the write-tool registration
contains `restore_file`. The connected server therefore still needs a restart
and client reconnect/tool-list refresh. Until the tool appears in the live
list, files soft-deleted through that connection cannot be restored through an
MCP tool; keep the returned `trash_path` for recovery from `.trash` on disk.

The search walker was changed to visit immediate files before descending and
to skip common dependency and cache directories, preventing large trees such
as `.venv` from consuming the scan cap before root-level files are searched.

## Pending

- Restart the running MCP server, reconnect the client, and confirm
  `restore_file` appears in its tool list.
- Verify restoration through that connected tool before relying on it for
  recovery.
- No `git_commit` check was reported.
