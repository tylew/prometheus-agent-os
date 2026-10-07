#!/bin/zsh
# ---
# name: stop
# description: Stop the dispatcher loop and clear its control workspace token; unit workspaces are untouched.
# usage: stop.sh
# ---
exec python3 "${0:A:h:h:h:h}/lib/dispatch.py" stop "$@"
