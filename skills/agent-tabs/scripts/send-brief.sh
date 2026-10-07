#!/bin/zsh
# ---
# name: send-brief
# description: Prompt an agent with one line pointing at its brief file and confirm the prompt landed by agent state (working|blocked), never by return value; no re-send on timeout.
# usage: send-brief.sh <pane-id> <brief-path>
# ---
exec python3 "${0:A:h:h:h:h}/lib/units.py" send-brief "$@"
