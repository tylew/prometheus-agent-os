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
close-unit.sh <workspace-id | plan-<slug>> [--force]
```

- **Names** — `sc-#####-<slug>` (one story) · `<theme-slug>` (story set) · `<goal-slug>` ·
  `review-<root-pr>-<slug>` (a stack under review) · `plan-<slug>` (planning).
- **Planning units are tabs**, not workspaces: `create-unit.sh plan-<slug> planning <project>` opens a
  `plan-<slug>` tab in the control workspace (the seat's) and puts the unit tokens on the planner's pane.
  `close-unit.sh plan-<slug>` closes that tab. A delivery unit created for a story removes it from every
  planning unit's `stories`.
- **Tokens** (source `prometheus`) — workspace: `unit`, `kind`, `project` (a registry key), `stories`,
  `prs`, `stage`; panes: `role`, `item`, `pr`, `worktree`. One writer each: `create-unit.sh` sets the
  workspace tokens; the lead keeps `stage`, `stories`, `prs` current; the session-role hook sets `role`.
- **Lead** — a delivery workspace's first tab, renamed `pm`, runs `lib/launch.sh pm`.
  `--brief` delivers the brief once the agent reaches its prompt.
- **Close** — refused while a role pane is `working` or `blocked`, or for a workspace without unit tokens.
  Before closing, the lead has removed its worktrees and has no librarian run in flight.
- The operator defines units: never carve, merge or add to one without them.
