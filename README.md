# prometheus

Role-based delivery hierarchy on Herdr. Design:
`docs/specs/workspace/prometheus/design.md`.

**Inactive by default.** Not in `enabledPlugins`, not in the marketplace. Loads only per launch:

```sh
claude --plugin-dir plugins/prometheus --agent prometheus:orchestrator
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

Every tab starts at `$WORKSPACE` with `claude --plugin-dir plugins/prometheus --agent prometheus:<role>`.
No state files: ownership + stage are Herdr tokens; each agent's context is its Claude session.

Layout + phase status: the design's *File layout*. Self-contained: no other plugin is required.
