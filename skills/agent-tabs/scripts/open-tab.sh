#!/bin/zsh
# ---
# name: open-tab
# description: Open a tab labeled <label> in the unit workspace, cwd $WORKSPACE, start lib/launch.sh <role> (role env, merged settings, dontAsk for depth-3) with the project's registry validation commands appended to the role's allow-list; write the pane's role/item/pr/worktree tokens; print the pane id.
# usage: open-tab.sh <workspace-id> <label> <pm|planner|implementor|reviewer> [--item <slug>] [--pr <owner/repo#n>] [--worktree <abs>] [--allow <rule>]...
# ---
exec python3 "${0:A:h:h:h:h}/lib/units.py" open-tab "$@"
