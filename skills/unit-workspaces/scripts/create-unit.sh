#!/bin/zsh
# ---
# name: create-unit
# description: Create a unit workspace labeled <name>, cwd $WORKSPACE, tagged via herdr workspace report-metadata --source prometheus with unit, kind, project, stories, prs; open its first tab — pm running prometheus:project-manager, or planner running prometheus:planner for kind planning; print the workspace id.
# usage: create-unit.sh <name> <story|story-set|goal-set|review> <project> [--stories sc-1,sc-2] [--prs owner/repo#1,…] [--brief <path>]
# ---
exec python3 "${0:A:h:h:h:h}/lib/units.py" create "$@"
