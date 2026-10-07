#!/bin/zsh
# ---
# name: compact-agent
# description: Send /compact <keep-focus> to an agent only when it is idle at a boundary; refuses mid-edit (working state).
# usage: compact-agent.sh <pane-id> <keep-focus...>
# ---
exec python3 "${0:A:h:h:h:h}/lib/units.py" compact "$@"
