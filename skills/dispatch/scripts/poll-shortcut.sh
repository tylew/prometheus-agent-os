#!/bin/zsh
# ---
# name: poll-shortcut
# description: Emit one JSON line per story owned by or assigned to the operator changed since the cursor, via one claude -p call (Haiku, --strict-mcp-config with only the Shortcut MCP, --json-schema).
# usage: poll-shortcut.sh   (forces a poll now; SHORTCUT_INTERVAL paces it inside the loop)
# ---
exec python3 "${0:A:h:h:h:h}/lib/events.py" poll-shortcut "$@"
