#!/bin/zsh
# ---
# name: rounds
# description: The PM's control over review rounds that open themselves — hold a PR out of them (veto), release it, open the next round now (own PR, after the round comment), or list the loops.
# usage: rounds.sh hold <owner/repo#n> [--off] | rounds.sh next <owner/repo#n> | rounds.sh list
# ---
exec python3 "${0:A:h:h:h:h}/lib/rounds.py" "$@"
