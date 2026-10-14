# Project Tracking

Last reviewed: 2026-10-14

## Current snapshot

- **Phase:** Maintenance after M5 (authenticated shared-workspace server).
- **Repository:** `main` tracking `origin/main`; working tree clean at review time.
- **Latest commit:** `07b9d71` — Update documentation and tests for authentication and tool exposure; refine workflow descriptions.
- **Scope:** Python MCP server with 10 authenticated tools, workspace sandbox, JSONL audit logging, and PM2/ngrok deployment guidance.
- **Latest local verification:** 224 passed, 7 skipped in 13.97s (2026-10-14, user-provided run after the maintenance changes). The seven skips are symlink cases on Windows.

## Improvement backlog

| Priority | Item                                                                                                       | Why it matters                                                                                           | Suggested completion check                                                                                              | Status |
| -------- | ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------ |
| P1       | Add CI for supported Python versions on Windows and Linux; run the full suite on a symlink-capable runner. | The documented Windows run skips symlink security cases, and there was no CI workflow in the repository. | CI is green on both OSes and all symlink cases execute on Linux.                                                        | Workflow is configured for Windows/Linux and Python 3.10–3.14. Local Windows run: 224 passed, 7 skipped. Hosted CI pending. |
| P1       | Reduce sandbox TOCTOU exposure for deployments where untrusted processes can modify the workspace.         | Path validation resolves symlinks before later filesystem operations; a path can change in between.      | Race-resistant operations with regression coverage, or a strictly enforced deployment boundary excluding other writers. | Open. Trusted-account boundary is documented but not enforced; hostile path replacement remains possible. |
| P2       | Remove the unconditional `if True:` wrappers in `server/tools/git_tools.py`.                               | They obscure the tool registration flow and look like remnants of the removed role gating.               | Registration is direct and tool exposure checks pass.                                                                   | Implemented in `git_tools.py`; local suite passed, hosted CI pending. |
| P2       | Define audit-log retention and failure behavior.                                                           | Unbounded JSONL output and process-local locking leave growth and multi-process behavior unspecified.    | Documented bounded rotation, retention, failure behavior, and process model.                                            | Implemented: 10 MiB rotation, five backups, single-process guidance, fail-closed behavior. Local suite passed. |
| P2       | Make deployment health checks and public-host changes easier to operate.                                   | The authenticated `/health` endpoint and changing ngrok hostname need a safe recovery procedure.         | Token-safe health check, hostname update, restart, and MCP verification are documented.                                 | Recovery steps documented; deployment walkthrough remains pending. |
| P3       | Add automated code-quality checks and a dependency update cadence.                                         | The project needs repeatable quality checks and a review process for pinned dependencies.                | CI runs lint checks; dependency update process is recorded.                                                             | Ruff passes locally and runs in CI; monthly Dependabot is configured. Type checking remains deferred. |

## Review cadence

At each maintenance review, update this snapshot and backlog, verify the recorded test/deployment evidence, and add dated decisions or milestones to `examples/workspace/` when the live workspace is being tracked.

## Implementation plan

Work in the sequence below. The P1 work establishes a dependable security and regression baseline before lower-risk cleanup and operations work. Keep each phase reviewable as a small change; update its status and evidence here when completed.

### Phase 1 — Establish cross-platform CI (P1)

1. Confirm the supported Python versions from the project’s actual dependency and runtime requirements; keep the initial matrix small and explicit.
2. Add a GitHub Actions workflow for pushes and pull requests across Windows and Linux and Python 3.10–3.14. Install from `requirements/requirements-lock.txt` and run `python -m pytest -q`.
3. Identify the symlink skips in `tests/`; configure the Linux job so those cases run, and make the Windows job report skips clearly rather than treating them as coverage.
4. Run the workflow on a branch, fix environment-specific failures, then record the successful commit and test totals here.

**Done when:** the full suite passes on both OSes and the symlink cases execute on Linux.

### Phase 2 — Close or explicitly contain the sandbox race (P1)

1. Map each filesystem tool’s sequence from `Sandbox.resolve()` through open, read, write, move, or delete. Identify which operations are vulnerable if a path or parent directory is replaced between validation and use.
2. Decide the supported threat model: whether any process outside this server may write to `WORKSPACE_ROOT`. If the answer is no, make that a clear deployment invariant and enforce workspace ownership/permissions where practical.
3. If untrusted concurrent writers are in scope, design an OS-specific safe file-operation layer (for example, directory-handle-relative operations with no-follow checks) and document platform support before implementing it. Avoid treating another path check as a race fix.
4. Add targeted regression cases for path replacement and symlink escapes on supported platforms, then run the full CI matrix.
5. Update `docs/SECURITY.md` with the residual limits and operational requirements.

**Done when:** the threat model is explicit and either the supported deployment prevents untrusted workspace mutation or the relevant file operations are race-resistant with regression coverage.

### Phase 3 — Simplify tool registration (P2)

1. Remove the unconditional `if True:` wrappers from `server/tools/git_tools.py` and dedent the enclosed registrations.
2. Confirm all Git tools are registered exactly once and retain the intended authentication/tool surface.
3. Run the relevant Git/tool registration tests and the full CI suite.

**Done when:** registration is direct and the existing tool exposure checks pass.

### Phase 4 — Specify audit operations (P2)

1. Set the supported server process count to one. If multiple processes become necessary, replace the process-local logging/rotation design with a process-safe approach.
2. Set bounded rotation and retention; specify archive/deletion, permissions, and disk-full behavior.
3. Implement the selected policy without logging secrets or raw bearer tokens. Add focused checks for rotation and concurrent writers if those modes are supported.
4. Document configuration and recovery steps in `docs/DEPLOYMENT.md`.

**Done when:** operators know how logs rotate, how long they are kept, and what happens when logging cannot write; behavior matches the documented process model.

### Phase 5 — Improve deployment health and recovery (P2)

1. Document token-safe health checks that do not put the bearer token in command history or process arguments; prefer a local environment-backed request or an approved secret store.
2. Add clear steps to obtain the current ngrok hostname, update `PUBLIC_HOSTNAME`, restart PM2, and verify both health and authenticated MCP initialization.
3. Confirm expected behavior for stale hostnames and invalid configuration at startup; make errors actionable without exposing secrets.
4. Walk through the recovery instructions on a local or staging deployment and record any manual assumptions.

**Done when:** a maintainer can detect an unhealthy service and recover from a hostname change using the documented steps without exposing the token.

### Phase 6 — Add maintainability checks and dependency routine (P3)

1. Use Ruff's default lint rules as the initial actionable baseline; expand checks only after addressing current findings.
2. Add linting to CI. Defer a type checker until its scope/configuration can be introduced without concealing existing type issues.
3. Record how to review dependency updates: update the lock file, inspect security/runtime changes, run the full matrix, and review the diff before merging.
4. Decide whether automated update PRs fit the project’s maintenance capacity; enable them only with a clear review owner.

**Done when:** CI runs the agreed quality checks and dependency updates have a repeatable, documented review path.

## Execution tracking

| Phase                       | Status                            | Evidence / next action                                                                                                                                  |
| --------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Cross-platform CI        | Local suite passes; hosted run pending | User ran the suite on the current Windows environment: 224 passed, 7 skipped in 13.97s. `.github/workflows/ci.yml` covers Python 3.10–3.14 on Windows and Linux; hosted CI remains pending. |
| 2. Sandbox race             | Partially addressed; race remains | `docs/SECURITY.md` defines the trusted OS-account boundary. ACL setup is an operator responsibility; operations remain vulnerable to a hostile concurrent writer under an authorized account. |
| 3. Git registration cleanup | Implemented; tests pending in CI | Removed unconditional wrappers from `server/tools/git_tools.py`; Git tool registration checks are part of the CI suite. |
| 4. Audit operations         | Implemented; behavior tests pending in CI | `server/audit.py` rotates at 10 MiB with five backups; docs require one process and describe disk-full behavior. |
| 5. Deployment recovery      | Documented; walkthrough pending | `docs/DEPLOYMENT.md` now includes an interactive token prompt and recovery flow. |
| 6. Quality and dependencies | Ruff passes locally; type checking deferred | Monthly Dependabot updates are configured. Ruff check passed locally; CI runs lint. Review dependency PRs before merge. |

### 2026-10-14 implementation continuation

- Installed the declared Ruff dev dependency in the local ignored virtualenv.
- Ruff initially found two unused imports; removed them. `ruff check server tests` now passes.
- `git diff --check` passes. The test suite and hosted CI were not run in this continuation.
- The sandbox race is still open. Documentation describes the operational trust boundary, but it does not enforce ACLs or prevent hostile path replacement.
- User ran `.venv\Scripts\python.exe -m pytest -q`: 224 passed, 7 skipped in 13.97s. The skipped symlink cases still need a Linux CI result.
