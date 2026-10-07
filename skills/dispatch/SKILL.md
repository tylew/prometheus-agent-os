---
name: dispatch
description: "The dispatcher — the only watcher; no agent polls, Monitors or loops. A lock-guarded script loop in the control workspace that polls GitHub (review requested, authored PRs), Shortcut (claude -p over MCP) and every agent pane's state (herdr api snapshot), matches each event to a unit workspace by story id or PR stack, routes matched events to the unit's pm pane by its tokens (delivered only in a safe state, coalesced per tick, heartbeat on stalls), triages unmatched ones with a one-shot claude -p, auto-creates review units, sends other proposals to the seat, resumes dead PMs, and settles bound KB decisions when a story reaches Completed or Won't Fix (kb.py inbox settle --story)."
---

# dispatch

The dispatcher is the only watcher. No agent polls, arms a `Monitor`, runs `/loop` or background-waits.
Scripts: `$CLAUDE_PLUGIN_ROOT/skills/dispatch/scripts/` (thin wrappers over `lib/dispatch.py` and `lib/events.py`).

## Start, stop, status (the seat)

```
begin.sh                 one dispatcher per Herdr session, in a `dispatcher` tab of the seat's workspace
stop.sh                  stop it; unit workspaces untouched
../../../lib/dispatch.py status
```
Env: `INTERVAL` (s, default 60), `HEARTBEAT` (min, 30), `SHORTCUT_INTERVAL` (s, 300),
`PROMETHEUS_NEW_PER_TICK` (3), `PROMETHEUS_STATE_DIR` (default `~/.claude/prometheus`).

## One tick

1. **Poll** — GitHub (`gh`, the registry's editable repos only): PRs with the operator's review requested,
   PRs the operator authored, every PR a unit holds. Shortcut: one `claude -p` (Haiku, Shortcut MCP only,
   read-only tools). Agent panes: one `herdr api snapshot`, `agent_status` diffed.
2. **Filter** — only next-move changes: CI terminal, review, new comment, merged / closed, new commits,
   draft ↔ ready, story state, agent state.
3. **Route** — by tokens: story id → `stories`, PR (or any PR in its stack) → `prs`, then the unit's
   `pm` (or `planner`) pane. Two units claiming one stack → conflict to the seat; never split.
4. **Triage** the unmatched new — `prometheus:triage`, fresh per event; verdict validated in code.
   `ignore` remembered · `attach` appends the token · `new` review request → review unit created for the
   whole stack · any other `new` → proposal to the seat · invalid → `untriaged` to the seat.
   Auto-create is held while any `pm`/`planner` tab sits in a workspace without unit tokens.
5. **Settle** — story Completed / Won't Fix → `kb.py inbox settle`.
6. **Heartbeat** · **Health** (a lead whose agent exited → `claude --resume <session>`) · **Deliver**.

## Delivery

Per pane, at most one line per tick (`templates/event-line.md`), details in the file it names. Only when
the agent is `idle`, `done` or `working` (Claude Code queues typed input); never `blocked` — typed text
would answer the open dialog. Undelivered lines wait in the outbox.

## Messaging — `send.sh`

```
send.sh --role pm "<one line>"                  to your own unit's lead
send.sh --role planner --unit <label> "<line>"  to another unit's role
send.sh --role seat "<line>"                     to the operator's seat
send.sh --pane <id> "<line>"
```
Tagged `[prometheus] from <role>@<unit>:`. The only way one agent messages another.

## Proposals — the seat answers

`proposal.sh approve <id>` creates the unit and queues its brief; `proposal.sh decline <id>` ignores the
subject for good.
