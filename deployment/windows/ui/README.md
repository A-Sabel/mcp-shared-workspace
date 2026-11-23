# Workspace Control UI

The Windows control panel is split into visual modules so layout and styling can
change independently of server lifecycle and process-management code.

## Structure

- `main-form.ps1` — creates the form and tab container, then loads the pages
  and shared theme.
- `pages/workspace-page.ps1` — assembles the Workspace tab from components.
- `pages/usage-page.ps1` — usage audit table, refresh action, and benchmark
  summary.
- `components/header.ps1` — title, service status, server URL, and appearance
  selector.
- `components/workspace-selector.ps1` — workspace picker, path fields, and
  folder registration UI.
- `components/action-buttons.ps1` — start, pause, and exit actions.
- `components/activity-log.ps1` — activity log control.
- `theme/theme.ps1` — Dark/Light palettes and recursive WinForms styling.

## Editing guidance

- Keep process startup/shutdown, timers, settings, workspace registry operations,
  and application launch in `../workspace-control.ps1`.
- Keep visual controls and their event wiring in the relevant component or page.
- Use `$script:` scope for controls accessed by operational functions in the
  parent script.
- UI files are dot-sourced, so they share the caller's script scope. Resolve
  nested modules relative to the current file's `$PSScriptRoot`.
- Keep the accent color `#DA0037` consistent in both themes.

The launcher remains `../start-workspace-hidden.vbs`; it still starts
`../workspace-control.ps1`.
