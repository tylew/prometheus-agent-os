# prometheus

Role-based delivery hierarchy, successor to `voltus-besstie`. Design:
`docs/specs/workspace/prometheus/design.md`.

**Inactive by default.** Not in `enabledPlugins`, not in the marketplace. Loads only per launch:

```sh
claude --plugin-dir plugins/prometheus --agent prometheus:orchestrator
```

## Topology (Herdr)

```
control workspace (operator)        panes: orchestrator, orchestrator, …
  └─ unit workspace "<unit-name>"   one per unit, owned by the orchestrator that created it
       ├─ tab pm                    project-manager — the orchestrator's only contact
       ├─ tab impl-<item>           implementor, fresh per work item
       ├─ tab review-<pr>           reviewer, fresh per independent round
       └─ librarian                 background subagent of the PM
```

Every tab starts at `$WORKSPACE` with `claude --plugin-dir plugins/prometheus --agent prometheus:<role>`.
Local state: `~/.claude/prometheus/orchestrators/<id>.md`, `~/.claude/prometheus/units/<unit>.md`.

Layout + phase status: the design's *File layout*. `voltus-besstie` must stay enabled: the agents load its skills for procedure.
