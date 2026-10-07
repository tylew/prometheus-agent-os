#!/bin/zsh
# ---
# name: pr-stack
# description: Print every PR in a PR's stack: walk baseRefName down to the default branch, then collect PRs whose base is any member's head.
# usage: pr-stack.sh <owner/repo> <number>
# ---
exec python3 "${0:A:h:h:h:h}/lib/events.py" pr-stack "$@"
