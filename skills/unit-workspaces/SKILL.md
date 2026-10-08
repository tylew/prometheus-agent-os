---
name: unit-workspaces
description: "Unit workspace mechanics for the dispatcher and seat: one Herdr workspace per epic (the unit), named for it, its prometheus tokens (unit, kind, epic, project, stories, prs, stage, stages), its first tab (pm); list live units, close one when its epic ends, and fold units of the older kinds into their epics."
---

# unit-workspaces

One Herdr workspace per unit, named for it, tagged with prometheus tokens. Scripts:
`$CLAUDE_PLUGIN_ROOT/skills/unit-workspaces/scripts/`.

```
create-unit.sh <name> epic <project> --epic <id> [--stories sc-1,sc-2] [--prs o/r#1,…] [--brief <path>]
fold.sh plan | fold.sh run --epic <id>        (dispatch/scripts) older units → their epic's unit
list-units.sh [--json]
close-unit.sh <workspace-id> [--force]
```

- **Names** — `epic-<id>-<slug>`. Units of the older kinds (`story` · `story-set` · `goal-set` · `review`)
  run until folded (`fold.sh`), and are never created new.
- **Tokens** (source `prometheus`) — workspace: `unit`, `kind`, `epic`, `project` (a registry key),
  `stories`, `prs`, `stage`, `stages` (`sc-1=review,sc-2=implement`); panes: `role`, `item`, `pr`, `worktree`. One writer each: `create-unit.sh` sets the
  workspace tokens; the lead keeps `stage`, `stories`, `prs` current with `dispatch/scripts/unit-tokens.sh`; the session-role hook sets `role`.
- **Lead** — a delivery workspace's first tab, renamed `pm`, runs `lib/launch.sh pm`.
  `--brief` delivers the brief once the agent reaches its prompt.
- **Close** — refused while a role pane is `working` or `blocked`, or for a workspace without unit tokens.
  Before closing, the lead has removed its worktrees and sent its last decision batch to the librarian.
- **The dispatcher opens epic units** on the first event in an epic and appends every story and PR of the
  epic as its events arrive; the seat opens one by hand only for "plan X" in an epic with no unit yet.
