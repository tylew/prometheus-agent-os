#!/bin/zsh
# ---
# name: dispatcher
# description: The loop: lock (one per Herdr session) → poll → match → route / triage → create or propose → health → settle (kb.py inbox settle --story on Completed / Won't Fix), every INTERVAL seconds. Writes the control workspace token dispatcher=running.
# usage: [INTERVAL=<s>] dispatcher.sh
# ---
echo "dispatcher: not implemented" >&2; exit 1
