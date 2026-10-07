#!/bin/zsh
# ---
# name: heartbeat
# description: For each unit with work in flight and no change for HEARTBEAT minutes, queue one 'no movement on <subject> for N min' event to its PM.
# usage: [HEARTBEAT=<min>] heartbeat.sh
# ---
exec python3 "${0:A:h:h:h:h}/lib/dispatch.py" heartbeat "$@"
