---
name: dispatch
description: "The dispatcher — the only watcher; no agent polls, Monitors or loops. A lock-guarded script loop in the control workspace, woken by Herdr events, that polls GitHub (review requested, authored PRs), Shortcut (claude -p over MCP) and every agent pane's state (herdr api snapshot), matches each event to a unit workspace by story id or PR stack, routes matched events to the unit's pm pane by its tokens (delivered only in a safe state, coalesced per tick, heartbeat on stalls), triages unmatched ones with a one-shot claude -p, auto-creates review units, sends other proposals to the seat, resumes dead PMs, keeps a restore image to bring units back after a Herdr restart, delivers agents' needs-you flags to the seat, and settles bound KB decisions when a story reaches Completed or Won't Fix (kb.py inbox settle --story)."
---

# dispatch

The dispatcher is the only watcher. No agent polls, arms a `Monitor`, runs `/loop` or background-waits.
Scripts: `$CLAUDE_PLUGIN_ROOT/skills/dispatch/scripts/` (thin wrappers over `lib/dispatch.py` and `lib/events.py`).

## Start, stop, status (the seat)

```
begin.sh                 librarian + map tabs beside the seat, restore, then one dispatcher per Herdr session
stop.sh                  stop it; unit workspaces untouched
restore.sh [--list] [--unit <name>] [--forget <name>]   units a Herdr restart took
map.sh [--unit <ws>] [--split]                           the map (drill-down + live preview), here or beside the caller
../../../lib/dispatch.py status
```
Env: `INTERVAL` (s, default 60), `HEARTBEAT` (min, 30), `SHORTCUT_INTERVAL` (s, 1800),
`PROMETHEUS_NEW_PER_TICK` (3), `PROMETHEUS_STATE_DIR` (default `~/.local/state/prometheus`),
`PROMETHEUS_FILTER` (regex on PR / story titles — trial runs act only on matches).

## One tick

The loop sleeps on a Herdr event subscription (`lib/herdr.py`): an agent state change, a pane opened or
closed wakes it within a second for an **agent tick** (agent poll + deliver). A **full tick** (below) runs
every `INTERVAL`. No socket → full ticks only.

1. **Poll** — GitHub (`gh`, the registry's editable repos only): PRs with the operator's review requested,
   PRs the operator authored, every PR a unit holds. Shortcut: one `claude -p` (Haiku, Shortcut MCP only,
   read-only tools). Agent panes: one `herdr api snapshot`, `agent_status` diffed.
2. **Filter** — only next-move changes: CI terminal, review, new comment, merged / closed, new commits,
   draft ↔ ready, story state, agent state.
3. **Route** — by tokens: story id → `stories`, PR (or any PR in its stack) → `prs`; else by **epic**: the
   event's stories → their epic (`story_epic` cache: the Shortcut poll returns epic ids; uncached stories get
   one batched read-only lookup per tick) → the unit whose `epic` token matches. The story and stack join
   that unit's tokens. Two units claiming one stack → conflict to the seat; never split.
4. **Epic units open themselves** — an unmatched event whose story has an epic opens `epic-<id>-<slug>` at
   once (a review request, an owned-paths PR — polled every `OWNED_INTERVAL`, 600 s, first poll a baseline
   line to the seat — or a story of the operator's). A story with **no epic**, or a PR with **no story**,
   goes to the seat once to be homed and routes on its next change. Opening is held while units await
   restore or carry no tokens. (`PROMETHEUS_EPIC_UNITS=0` restores the older triage → proposal path.)
5. **Settle** — story Completed / Won't Fix → `kb.py inbox settle`.
6. **Heartbeat** · **Health** (a lead whose agent exited → `claude --resume <session>`) · **Deliver**.
7. **Restore image** — per live unit: tokens, and per agent tab its label, pane tokens and Claude session.
   A unit in the image with no live workspace is *pending restore*: events for its PRs / stories are held
   for its PM (`restore_backlog`), and nothing is auto-created, until `restore.sh` brings it back or
   `--forget` drops it. `close-unit.sh` drops the image.

## Delivery

Per pane, at most one line per tick (`templates/event-line.md`), details in the file it names. Only when
the agent is `idle`, `done` or `working` (Claude Code queues typed input); never `blocked` — typed text
would answer the open dialog; an open choice dialog or text on the prompt line also holds it. Prompts go in
with `herdr agent prompt --wait` (resent only on `agent_prompt_stalled`). Undelivered lines wait in the
outbox.

## Messaging — `send.sh`

`send.sh` and `report.sh` are on every agent's PATH. Call them bare, one command per Bash call — never
`cd … &&`, chained or by relative path; the depth-3 allow-lists match only `send.sh …` / `report.sh …`.

**Command form (dontAsk roles).** Never `cd` — after `builtin cd` every relative path or `git` is denied,
a relative `cd` too, and the tab already starts in its worktree. Elsewhere: `git -C <abs>` and absolute paths. `&&` / `;` and
pipes into `grep` / `head` / `wc` pass when every part is allowed. Files outside the worktree (plugin
skills, briefs, `docs/kb/`) → the Read / Grep tools, not `cat` / `grep`. No `$(…)`, no `awk`. A denied form is rewritten in this shape,
never dropped silently.

```
send.sh --role pm "<one line>"                  to your own unit's lead
send.sh --role planner --unit <label> "<line>"  to another unit's role
send.sh --role seat "<line>"                     to the operator's seat
send.sh --pane <id> "<line>"
```
Tagged `[prometheus] from <role>@<unit>:`. The only way one agent messages another.

## Quick work — `quick.sh` (the seat)

```
quick.sh <slug> "<the ask>"     a quick-<slug> runner tab beside the seat; exports in <state>/exports/<slug>/
```
Artifacts only: the runner never edits a project, commits or writes the tracker; code changes come back as
a proposed unit. Its permission prompts reach the seat as needs-you; its result is a `done` line to the seat.

## Instruction gaps — up, never fixed in place

Only a configurator changes prometheus (the edit guard enforces it), and only the seat opens one. Any agent
that hits a wrong or missing instruction, a denial its work needed, or a gap worth codifying reports it with
the evidence and carries on with what it can:

```
worker (implementor · reviewer · planner) → its PM        send.sh --role pm   "gap: <what> — evidence: <denial / path>"
PM · runner                                → the seat      send.sh --role seat "gap: <what> — evidence: …"
seat: triage — gimme (mechanical: allow-list, path, script bug, lint) → configure.sh <slug> "<issue + evidence>"
               changes what an agent decides or does → one question to the operator first
```
The configurator proposes acceptance criteria; the seat signs off or raises concerns (for the operator).

## Quick work — `quick.sh` (the seat)

```
report.sh "<one line>"              your line on the map (status token)
report.sh --needs-you "<question>"  red flag + the question to the seat, with your pane id to answer
report.sh --clear
```
The needs-you flag clears when you next work. A PM / planner with the operator in its tab asks in place.

## Proposals — the seat answers

`proposal.sh approve <id>` creates the unit and queues its brief; `proposal.sh decline <id>` ignores the
subject for good.
