#!/bin/zsh
# ---
# name: respawn
# description: Restart an idle agent in place from its own session so it picks up changed instructions, settings or MCP access — the conversation is kept, the system prompt rebuilt. The seat runs it after a configurator change names the tabs to relaunch (the seat may respawn itself).
# usage: respawn.sh <pane-id> [--force]
# ---
exec python3 "${0:A:h:h:h:h}/lib/units.py" respawn "$@"
