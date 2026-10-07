#!/bin/zsh
# ---
# name: match-event
# description: Match one event to a unit workspace by story id (stories token) or by any PR in its stack (prs token); print the workspace id, CONFLICT if two units match, or nothing.
# usage: match-event.sh <event-json>
# ---
exec python3 "${0:A:h:h:h:h}/lib/events.py" match "$@"
