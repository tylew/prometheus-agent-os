#!/bin/zsh
# ---
# name: poll-agents
# description: One herdr api snapshot per tick; diff every unit-workspace pane's agent_status against the last tick and emit one JSON line per change (pane, role, item, old, new).
# usage: poll-agents.sh
# ---
exec python3 "${0:A:h:h:h:h}/lib/dispatch.py" poll-agents "$@"
