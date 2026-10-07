#!/bin/zsh
# ---
# name: health
# description: For each unit workspace, check its pm pane; if gone or dead, open a new pm tab with claude --resume <agent_session> from herdr api snapshot.
# usage: health.sh
# ---
exec python3 "${0:A:h:h:h:h}/lib/events.py" health "$@"
