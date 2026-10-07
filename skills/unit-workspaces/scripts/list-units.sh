#!/bin/zsh
# ---
# name: list-units
# description: List live unit workspaces (those carrying prometheus unit tokens): workspace id, label, kind, project, stories, prs, stage, pm agent status.
# usage: list-units.sh [--json]
# ---
exec python3 "${0:A:h:h:h:h}/lib/units.py" list "$@"
