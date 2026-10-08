#!/bin/zsh
# ---
# name: report
# description: An agent's own line on the map — sets the `status` token on the caller's pane. --needs-you also sets `needs` (a red flag on the map) and queues the question to the seat with the pane id to answer; the flag clears when the agent next works. --clear removes both. --holds <owner/repo#n> adds the PR to the pane's `pr` token: its CI, review and comment events come to this tab.
# usage: report.sh [--needs-you] <one line> | report.sh --holds <owner/repo#n> | report.sh --clear
# ---
exec python3 "${0:A:h:h:h:h}/lib/dispatch.py" report "$@"
