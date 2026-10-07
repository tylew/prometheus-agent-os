#!/bin/zsh
# ---
# name: kb
# description: The knowledge base's one entry point for agents (on their PATH) — every lib/kb.py subcommand, plus `proposal-path <name>`, which prints the absolute file an ingest proposal is written to (under the state dir; the only place a librarian may Write).
# usage: kb.sh <index|resolve|search|new|apply|inbox|check|proposal-path> [args]
# ---
exec python3 "${0:A:h:h:h:h}/lib/kb.py" "$@"
