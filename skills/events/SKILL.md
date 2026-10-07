---
name: events
description: "The PM's side of the dispatcher contract: the event line it receives (unit, kind, subject, change, details file), the event kinds (CI terminal, review, comment, merged/closed, story state, agent state incl. blocked, denied-action reports, heartbeat), and how to react to each — reading and resolving a blocked depth-3 pane included. Agents never poll, Monitor or loop — every wake is an operator message, a dispatcher event, or a heartbeat."
---

# events

What a lead (PM or planner) receives and how it reacts. It never polls: it wakes on the operator, a
dispatcher line, or a heartbeat, and ends its turn whenever it is waiting.

## The line

`[prometheus] <n> messages: <summary> — details: <path>` or a single `[prometheus] …` line. Read the details
file (JSON, one object per event with its source payload) before acting. Untagged input is the operator,
typing in your tab — answer in place.

| Kind | Example | React |
|---|---|---|
| `pr … ci pass / fail` | `pr o/r#12 ci fail` | fail → read the checks, brief the item's implementor; pass → is the round due? |
| `pr … review <who>:<state>` · `… new comment(s)` | | triage per the PM's *Review findings* table — critical fixed, high weighed, scope growth asked of the operator (batched), wrong findings pushed back on the thread or to the operator; fixes go to the item's implementor |
| `pr … merged / closed` | | close the item's tab and worktree; merged → advance the story (`tracker`) |
| `pr … new commits` · `ready for review` | | a review round may be due (`review`) |
| `story sc-… <old> → <new>` | | reconcile your plan with the board |
| `agent <label> working → idle / done` | | read the agent's artifact — completion is the artifact, not the state |
| `agent <label> … → blocked` | | `herdr agent read <pane>`; answer or dismiss within its brief (`herdr agent send-keys`), else refresh it and tell the seat |
| `from implementor@… / reviewer@…: denied: <action>` | | do it yourself if it is yours, re-brief, or escalate — and report the permission gap to the seat before closing the tab |
| `heartbeat: no movement in <unit>` | | check the agent or PR that should be moving; act or report the block |
| `Read your brief at <path> and begin.` | | the unit's brief — start the lifecycle |

## Handing off

Before passing work on: artifact complete? CI settled? round due? operator gate cleared? Review item N while
N+1 is built; restack N+1 only at its commit boundary. Report to the seat at gate crossings and blockers only.
