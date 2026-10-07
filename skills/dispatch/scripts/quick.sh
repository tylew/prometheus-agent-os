#!/bin/zsh
# ---
# name: quick
# description: The seat's quick-work path — open a `quick-<slug>` runner tab beside the seat for one small ask that is not delivery work (an export, a script or query run, a lookup), with its own exports folder and a brief holding the operator's words; the runner reports its artifact paths back to the seat. Close it with `units.py close-tab <workspace> quick-<slug>` once the result is back.
# usage: quick.sh <slug> <the ask, in the operator's words>
# ---
set -euo pipefail
[[ -n ${HERDR_WORKSPACE_ID:-} ]] || { echo "quick: not inside Herdr" >&2; exit 2; }
slug=${1:?usage: quick.sh <slug> <ask>}; shift
exec python3 "${0:A:h:h:h:h}/lib/units.py" quick "$HERDR_WORKSPACE_ID" "$slug" "$@"
