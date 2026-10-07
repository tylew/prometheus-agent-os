# prometheus

Role-based delivery hierarchy, successor to `voltus-besstie`. Design:
`docs/specs/workspace/prometheus/design.md`.

**Inactive by default.** Not in `enabledPlugins`, not in the marketplace. Loads only per launch:

```sh
claude --plugin-dir plugins/prometheus --agent prometheus:orchestrator
```

## Roles

| Agent | Runs as | Spawned by |
|---|---|---|
| `orchestrator` | the operator's window | operator |
| `project-manager` | dedicated window per unit (story · epic design · goal set) | orchestrator |
| `implementor` | dedicated window per work item | project-manager |
| `reviewer` | dedicated window per PR | project-manager |
| `librarian` | background subagent | project-manager |

Windows are Herdr panes (`voltus-besstie:integration-herdr`) launched with
`claude --plugin-dir plugins/prometheus --agent prometheus:<role>` plus a role brief.

`voltus-besstie` must stay enabled: the agents load its skills for procedure.
