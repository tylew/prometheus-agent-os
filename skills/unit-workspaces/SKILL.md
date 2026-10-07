---
name: unit-workspaces
description: "Unit workspace mechanics for the dispatcher and seat: create one Herdr workspace per unit (story, story set, planning effort, goal set, review stack), name it, write its prometheus tokens (unit, kind, project, stories, prs), open its first tab (pm, or planner for a planning unit), list live units, and close one when its unit ends."
---

# unit-workspaces

One Herdr workspace per unit, named for it, tagged with prometheus tokens. Scripts:
`$CLAUDE_PLUGIN_ROOT/skills/unit-workspaces/scripts/`.

```
create-unit.sh <name> <story|story-set|planning|goal-set|review> <project> [--stories sc-1,sc-2] [--prs o/r#1,…] [--brief <path>]
list-units.sh [--json]
close-unit.sh <workspace-id> [--force]
```

- **Names** — `sc-#####-<slug>` (one story) · `<theme-slug>` (story set) · `plan-<slug>` (planning) ·
  `<goal-slug>` · `review-<root-pr>-<slug>` (a stack under review).
- **Tokens** (source `prometheus`) — workspace: `unit`, `kind`, `project` (a registry key), `stories`,
  `prs`, `stage`; panes: `role`, `item`, `pr`, `worktree`. One writer each: `create-unit.sh` sets the
  workspace tokens; the lead keeps `stage`, `stories`, `prs` current; the session-role hook sets `role`.
- **Lead** — the first tab, renamed `pm` (or `planner` for `planning`), runs `lib/launch.sh <lead>`.
  `--brief` delivers the brief once the agent reaches its prompt.
- **Close** — refused while a role pane is `working` or `blocked`, or for a workspace without unit tokens.
  Before closing, the lead has removed its worktrees and has no librarian run in flight.
- The operator defines units: never carve, merge or add to one without them.
