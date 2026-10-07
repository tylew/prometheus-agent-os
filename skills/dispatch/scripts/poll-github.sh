#!/bin/zsh
# ---
# name: poll-github
# description: Emit one JSON line per PR with the operator's review requested or authored by the operator, changed since the cursor in ~/.local/state/prometheus/dispatch.json.
# usage: poll-github.sh   (prints one JSON event per line; advances cursors)
# ---
exec python3 "${0:A:h:h:h:h}/lib/events.py" poll-github "$@"
