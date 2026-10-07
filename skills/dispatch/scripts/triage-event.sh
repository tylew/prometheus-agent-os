#!/bin/zsh
# ---
# name: triage-event
# description: Run claude -p --agent prometheus:triage --json-schema templates/triage-result.json on one unmatched event plus the live units; print the result JSON.
# usage: triage-event.sh <event-json>   (prints the verdict; acts on nothing)
# ---
exec python3 "${0:A:h:h:h:h}/lib/events.py" triage "$@"
