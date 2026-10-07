#!/bin/zsh
# ---
# name: refresh-agent
# description: Retire an agent's session and start a fresh one in a new tab with the same label and a new brief — used per work item and per adversarial judging round.
# usage: refresh-agent.sh <workspace-id> <label> <role> <brief-path>
# ---
exec python3 "${0:A:h:h:h:h}/lib/units.py" refresh "$@"
