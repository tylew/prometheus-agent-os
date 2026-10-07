#!/bin/zsh
# ---
# name: close-tab
# description: Close an agent tab whose work item merged or whose session is retired.
# usage: close-tab.sh <workspace-id> <label>
# ---
exec python3 "${0:A:h:h:h:h}/lib/units.py" close-tab "$@"
