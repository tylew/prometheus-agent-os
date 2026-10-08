---
name: agent-tabs
description: "Project-manager mechanics for agent tabs: open a named tab (impl-<item>, review-<pr>, validate-<pr>) in the unit workspace, start the role's claude agent (herdr agent start), deliver a brief file and confirm a turn started (herdr agent prompt --wait), and close the tab when its work ends."
---

# agent-tabs

The lead opens one tab per agent in its unit workspace. Scripts: `$CLAUDE_PLUGIN_ROOT/skills/agent-tabs/scripts/`.

```
open-tab.sh <workspace-id> <label> <implementor|reviewer|pm|planner> [--item <slug>] [--pr <o/r#n>] [--worktree <abs>] [--allow <rule>]...
send-brief.sh <pane-id> <brief-path>
close-tab.sh <workspace-id> <label>
```

- **Worktree first** — create the item's worktree completely (branch, `gt track`, the project's worktree
  setup — `branching`) before `open-tab.sh --worktree <abs>`, which links the registry's `worktree_links`
  (e.g. `js/node_modules`) into it. The tab starts in that worktree, so the implementor's plain `git` / `gt` act on it.
- **Labels** — `impl-<item-slug>`, `review-<pr#>`, `validate-<pr#>` (a reviewer on `templates/validate-brief.md`), `planner` (one per unit, opened when it needs stories). Labels may repeat across units; routing uses pane ids.
- **Launch** — `herdr agent start` with `lib/launch.sh <role> --args`: merged settings (other workflow plugins off
  for the session), `--name <label>`, and for implementor / reviewer `--permission-mode dontAsk` with
  `templates/settings/<role>.json`; role env comes from the tab. Returns once the agent takes input. Pass the
  project's validation commands as `--allow 'Bash(<cmd> *)'` (`registry.py field packages --key <project>`) for
  both implementor and reviewer.
- **Briefs** — written to a file from `templates/implementor-brief.md` / `reviewer-brief.md`, never pasted.
  `send-brief.sh` sends one line with `herdr agent prompt --wait`; Herdr confirms a turn started, and the
  line is resent only when Herdr reports the prompt stalled (at most 3 tries).
- **Brief contents** — absolute worktree path and ref; "never the project's main checkout; `samples/` is
  read-only"; the `branching` non-negotiables copied verbatim; the scenario; confirmed UI changes.
- Every later message to the agent goes through `send.sh`. Close a tab when its item merges or its session
  is retired.
