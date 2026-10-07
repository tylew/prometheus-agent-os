#!/bin/zsh
# ---
# name: deliver
# description: Deliver queued events to one pane: only when its agent is idle or working (never blocked — typed text would answer a dialog); coalesce to one line per tick with a details file; otherwise keep them in the outbox in dispatch.json.
# usage: deliver.sh <pane-id>
# ---
exec python3 "${0:A:h:h:h:h}/lib/dispatch.py" deliver "$@"
