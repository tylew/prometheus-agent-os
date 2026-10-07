# prometheus

Role-based delivery hierarchy on Herdr. Design:
`docs/specs/workspace/prometheus/design.md`.

**Inactive by default.** Not in `enabledPlugins`, not in the marketplace. Loads only per launch:

```sh
plugins/prometheus/lib/launch.sh seat
```

Then say **begin** (`/prometheus:begin`) to start the dispatcher.

## Topology (Herdr)

```
control workspace (operator)        panes: seat (orchestrator agent), dispatcher (script)
  └─ unit workspace "<unit-name>"   one per unit; review stacks created automatically
       ├─ tab pm                    project-manager — the only agent the seat addresses
       ├─ tab impl-<item>           implementor, fresh per work item
       ├─ tab review-<pr>           reviewer, fresh per independent round
       └─ librarian                 background subagent of the PM
```

Every tab runs `lib/launch.sh <role>` (`seat` · `planner` · `pm` · `implementor` · `reviewer`): it resolves `$WORKSPACE`,
sets `PROMETHEUS_ROLE`, merges `templates/settings/launch.json` (voltus-besstie disabled for the session) with the
role's allow-list, and adds `--permission-mode dontAsk` for implementor and reviewer.

**Trial period:** the workspace `CLAUDE.md` still loads and names voltus-besstie skills. Prometheus agents follow
their own instructions for role behavior; the workspace file is rewritten at cutover.
No state files: ownership + stage are Herdr tokens; each agent's context is its Claude session.

Layout + phase status: the design's *File layout*. Self-contained: no other plugin is required.
