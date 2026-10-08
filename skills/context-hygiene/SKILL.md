---
name: context-hygiene
description: "When to /compact an agent versus start it fresh, and how: fresh session per work item and per adversarial judging round, /compact only at quiet boundaries with a keep-focus, and session resume (claude --resume from the pane's agent_session) instead of any state file."
---

# context-hygiene

Scripts: `$CLAUDE_PLUGIN_ROOT/skills/context-hygiene/scripts/`.

```
compact-agent.sh <pane-id> <keep-focus...>        only at the agent's prompt (idle / done)
refresh-agent.sh <workspace-id> <label> <role> <brief-path>
```

| Situation | Do |
|---|---|
| a new work item | fresh implementor tab — never reuse a finished one |
| first review · re-review after major rework · a disputed finding | fresh reviewer session (`refresh-agent.sh`) — it must not have seen the author's reasoning |
| a long item between rounds or after a commit | `compact-agent.sh <pane> keep: <item>, <open findings>, <next step>` — never mid-edit |
| an agent that exited | the dispatcher resumes leads (`claude --resume <session>`); a depth-3 agent is refreshed with a new brief |

No state files: an agent's context is its Claude session; durable facts live in specs, Shortcut, git and
the KB; live facts in Herdr tokens. The seat holds nothing — `/clear` on it is always safe.

**Respawn** — `respawn.sh <pane> [--force]` restarts an idle agent on its own session with the current
instructions, settings and MCP access (`--resume … --system-prompt-snapshot off`); the conversation is kept. The
seat runs it after a configurator change.

**An epic PM compacts itself** between stories: write the epic file first (it is what survives), then
`compact-agent.sh --queue $HERDR_PANE_ID keep: epic <id>, read <epic file>, next: <step>` and end the turn —
the dispatcher delivers it once you are idle. Never mid-handoff.
