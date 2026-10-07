#!/bin/zsh
# ---
# name: proposal
# description: The seat's answer to a dispatcher proposal — approve creates the unit (workspace, tokens, lead tab, brief queued); decline records the subject as ignored so it is not triaged again.
# usage: proposal.sh <approve|decline> <proposal-id>
# ---
exec python3 "${0:A:h:h:h:h}/lib/events.py" proposal "$@"
