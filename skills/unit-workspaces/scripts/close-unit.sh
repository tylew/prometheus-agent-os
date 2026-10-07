#!/bin/zsh
# ---
# name: close-unit
# description: Close an owned unit workspace once its PM reports no librarian run in flight; refuses a workspace without prometheus unit tokens.
# usage: close-unit.sh <workspace-id> [--force]
# ---
exec python3 "${0:A:h:h:h:h}/lib/units.py" close "$@"
