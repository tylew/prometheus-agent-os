#!/bin/zsh
# ---
# name: session-role
# description: SessionStart: inside Herdr, when the session was started by lib/launch.sh (PROMETHEUS_ROLE set), tag the pane with its role (pane report-metadata --source prometheus --token role=<role>). Never blocks the session; no-op otherwise.
# usage: hooks.json → SessionStart
# ---
[[ ${HERDR_ENV:-} == 1 && -n ${PROMETHEUS_ROLE:-} && -n ${HERDR_PANE_ID:-} ]] || exit 0
herdr pane report-metadata "$HERDR_PANE_ID" --source prometheus --token "role=$PROMETHEUS_ROLE" >/dev/null 2>&1
exit 0
