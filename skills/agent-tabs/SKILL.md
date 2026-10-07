---
name: agent-tabs
description: "Project-manager mechanics for agent tabs: open a named tab (impl-<item>, review-<pr>) in the unit workspace, start the role's claude agent, deliver a brief file and confirm it landed by agent state, and close the tab when its work ends."
---

# agent-tabs

The lead opens one tab per agent in its unit workspace. Scripts: `$CLAUDE_PLUGIN_ROOT/skills/agent-tabs/scripts/`.

```
open-tab.sh <workspace-id> <label> <implementor|reviewer|pm|planner> [--item <slug>] [--pr <o/r#n>] [--worktree <abs>] [--allow <rule>]...
send-brief.sh <pane-id> <brief-path>
close-tab.sh <workspace-id> <label>
```

- **Labels** — `impl-<item-slug>`, `review-<pr#>`, `planner` (one per unit, opened when it needs stories). Labels may repeat across units; routing uses pane ids.
- **Launch** — `lib/launch.sh <role>`: role env, merged settings (voltus-besstie off for the session), and
  for implementor / reviewer `--permission-mode dontAsk` with `templates/settings/<role>.json`. Pass the
  project's validation commands as `--allow 'Bash(<cmd> *)'` (`registry.py field packages --key <project>`) for
  both implementor and reviewer.
- **Briefs** — written to a file from `templates/implementor-brief.md` / `reviewer-brief.md`, never pasted.
  `send-brief.sh` waits for the prompt, sends one line, and confirms it landed by state (`working` /
  `blocked`). It never re-sends: a timeout is reported, not retried.
- **Brief contents** — absolute worktree path and ref; "never the project's main checkout; `samples/` is
  read-only"; the `branching` non-negotiables copied verbatim; the scenario; confirmed UI changes.
- Every later message to the agent goes through `send.sh`. Close a tab when its item merges or its session
  is retired.
