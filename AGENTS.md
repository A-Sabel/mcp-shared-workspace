# Agent rules (keep token use low)

## Reading
- Find before reading: `search_files`, `list_files`, `get_file_outline`. Read only the needed line ranges (max 200 lines each; batch up to 5 with `ranges`).
- Never guess paths. Don't re-read a file you just wrote or patched.
- `get_workspace_context`: request only the sections you need.

## Editing
- `str_replace`: copy `old` exactly from `read_file` output (plain `\n`; line endings are preserved). It must match once, else add context or use `replace_all`.
- If an edit fails, re-read before retrying. Never resend the same text.
- Multi-line changes: `apply_patch` with standard unified diff (`--- a/p`, `+++ b/p`, `@@ -a,b +c,d @@`), not `*** Begin Patch`. Start line must be correct; header counts are not strict. A hunk with no old lines inserts after line `a`.
- New files: `write_file` with `create_only=true`. Pass `expected_hash` from your last read when others may be editing.
- `delete_file` is a soft delete: keep the returned `trash_path`.

## Safety
- `git_restore`: preview first. `git_status` fails if the workspace isn't a Git repo.
- `get_change_impact` / `find_symbol` take a real path or a simple identifier, not a description or a path with a colon.
- After edits, run `run_project_checks` if configured.
