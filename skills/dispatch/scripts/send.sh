#!/bin/zsh
# ---
# name: send
# description: Agent-to-agent message, in any direction (PM ↔ implementor/reviewer/planner, PM → seat): enqueue one line for a target pane — by pane id, or by role token within a unit (unit defaults to the sender's own workspace; role seat resolves to the control workspace) — in the dispatcher outbox. The dispatcher delivers it in a safe state, tagged with the sender's role and unit. The only way one agent messages another.
# usage: send.sh (--pane <id> | --role <pm|implementor|reviewer|planner|seat> [--unit <label>]) <message>
# ---
echo "send: not implemented" >&2; exit 1
