#!/bin/zsh
# ---
# name: send
# description: Agent-to-agent message, in any direction (PM ↔ implementor/reviewer/planner, PM → seat): enqueue one line for a target pane — by pane id, or by role token within a unit (unit defaults to the sender's own workspace; roles seat and librarian resolve to the control workspace) — in the dispatcher outbox. The dispatcher delivers it in a safe state, tagged with the sender's role and unit. The only way one agent messages another.
# usage: send.sh (--pane <id> | --role <pm|implementor|reviewer|planner|seat|librarian> [--unit <label>]) <message>
# ---
exec python3 "${0:A:h:h:h:h}/lib/dispatch.py" send "$@"
