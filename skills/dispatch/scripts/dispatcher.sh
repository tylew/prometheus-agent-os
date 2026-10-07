#!/bin/zsh
# ---
# name: dispatcher
# description: The only watcher in the system. Loop: lock (one per Herdr session) → poll (GitHub, Shortcut, agent panes) → filter to changes that alter a next move → route by tokens (unmatched → triage → create or propose) → settle (kb.py inbox settle --story on Completed / Won't Fix) → heartbeat → health → deliver (safe state, coalesced, outbox), every INTERVAL seconds. Writes the control workspace token dispatcher=running.
# usage: [INTERVAL=<s>] [HEARTBEAT=<min>] dispatcher.sh   (exit 3 if one is already running)
# ---
exec python3 "${0:A:h:h:h:h}/lib/dispatch.py" run "$@"
