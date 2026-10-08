#!/bin/zsh
# ---
# name: kb
# description: The knowledge base's one entry point for agents (on their PATH) — every lib/kb.py subcommand, with `apply` taking a proposal file; `proposal-path <name>` prints where agents Write it.
# usage: kb.sh <index|resolve|search|new|apply|inbox|check|proposal-path> [args]
# ---
exec python3 "${0:A:h:h:h:h}/lib/kb.py" "$@"
