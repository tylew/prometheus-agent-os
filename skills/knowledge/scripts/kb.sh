#!/bin/zsh
# ---
# name: kb
# description: The knowledge base's one entry point for agents (on their PATH) — every lib/kb.py subcommand, with `apply` taking a proposal file or the proposal JSON itself (agents pass it inline — they write no files); `proposal-path <name>` prints where a proposal file would go.
# usage: kb.sh <index|resolve|search|new|apply|inbox|check|proposal-path> [args]
# ---
exec python3 "${0:A:h:h:h:h}/lib/kb.py" "$@"
