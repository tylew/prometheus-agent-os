#!/bin/zsh
# ---
# name: route
# description: Resolve an event to its target pane: unit workspace by stories/prs tokens (PRs via their stack), then the pane whose role token is pm; print the pane id. Proposals and conflicts route to the seat pane.
# usage: route.sh <event-json>   (prints the target pane id; exit 1 with the reason on no match or CONFLICT)
# ---
exec python3 "${0:A:h:h:h:h}/lib/dispatch.py" route "$@"
