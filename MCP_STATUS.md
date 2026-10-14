# MCP Status and Testing

Date: 2026-10-14
Server: MCP Shared Workspace
Overall status: Connected and working, with two caveats below.

## Test Results
| Tool | Test | Result |
|------|------|--------|
| tool_search | Load workspace tools | Passed |
| list_files | List workspace root | Passed (17 items) |
| list_files | Glob `*.py` | Passed |
| write_file | Create `hello_world.py` | Passed (verified by read-back) |
| read_file | Read `hello_world.py` | Passed |
| str_replace | Edit a temp file | Passed (verified by read-back) |
| search_files | Search for edited text (path = file) | Passed |
| search_files | Search with `glob` set to a filename | Returned no matches (see caveats) |
| search_files | Search whole workspace | Passed (but includes `.venv` noise) |
| delete_file | Delete temp file | Passed (moved to `.trash/`) |
| git_status | Show branch and changes | Passed (branch `main`) |
| git_diff | Diff `hello_world.py` | Passed (no changes, file is untracked) |

## Not Tested (intentionally)
- git_commit: would modify repo history
- append_state: would modify shared handoff files

## Caveats
1. Earlier writes were lost. The first `hello_world.py` and `MCP_STATUS.md`
   reported "Wrote ..." but did not exist when listed afterward. Files
   written in this round were verified by reading them back. Cause unknown;
   possibly a workspace switch between sessions.
2. `search_files` with `glob` pointing at a single filename returned no
   matches, while using `path` for the same file worked.
3. The workspace has many uncommitted changes in `server/`, `docs/` and
   `deployment/`. None were touched during testing.
