#!/bin/zsh
# ---
# name: report
# description: An agent's own line on the map — sets the `status` token on the caller's pane. --needs-you also sets `needs` (a red flag on the map) and queues the question to the seat with the pane id to answer; the flag clears when the agent next works. --clear removes both. --holds <owner/repo#n> adds the PR to the pane's `pr` token: its CI, review and comment events come to this tab. --stopped / --idr / --done <file> (implementor): the file is kept in the engine inbox and its unit lead gets one line naming it; an IDR is checked first (lib/idr.py) and refused with the problems if it does not conform; a done report needs a clean, current proof.json beside it (lib/proof.py); a stop also flags the pane.
# usage: report.sh [--needs-you] <one line> | report.sh --holds <owner/repo#n> | report.sh --stopped|--idr|--done <file> | report.sh --clear
# ---
exec python3 "${0:A:h:h:h:h}/lib/dispatch.py" report "$@"
