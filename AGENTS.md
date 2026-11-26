# Agent rules

## Reading
- Find before reading: `search_files`, `list_files`, `get_file_outline`; then read only needed ranges (max 200 lines; batch up to 5 with `ranges`). Never guess paths. Don't re-read a file you just wrote or patched.
- `get_workspace_context`: request only the sections you need.
- `search_files`: literal, case-sensitive (`regex=true` + `(?i)` otherwise). A `[scan limit reached]` or per-file-limit note means partial results: narrow with `path=`/`glob=`. In globs, `*` stays within one directory; use `**` to recurse.
- `find_symbol`/`find_references`: simple identifier only (use `search_files` for phrases or dotted names); `path` may be a directory or a file.

## Editing
- `str_replace`: copy `old` exactly from `read_file` output; it must match once, else add context or use `replace_all`. If an edit fails, re-read before retrying; never resend the same text.
- Multi-line changes: `apply_patch` with standard unified diff (`--- a/p`, `+++ b/p`, `@@ -a,b +c,d @@`), not `*** Begin Patch`. Start line must be correct; header counts are not strict. A hunk with no old lines inserts after line `a`.
- New files: `write_file` with `create_only=true`. Pass `expected_hash` from your last read when others may be editing.
- `delete_file` is a soft delete: keep the returned `trash_path`.

## Checks
- Run `run_project_checks(["pytest"], max_output_chars=2000)` once at the end of a task that changed code or tests. Skip for docs/markdown/config-only changes. `ruff` skips here (no config).

## Safety
- `git_restore`: preview first. `git_status` fails outside a Git repo.
- `get_change_impact` takes a real path or a simple identifier, not a description or a path with a colon.
- Commit only when asked; use `git_commit` with explicit paths.

## Replies
- Final reply: what changed, test result, open items only.
