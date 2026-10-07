#!/bin/zsh
# ---
# name: redash
# description: Read-only Redash for agents (on their PATH) — find, inspect and run saved queries into a CSV. Wraps lib/redash.py.
# usage: redash.sh queries [--search T] | redash.sh query <id> | redash.sh run <id> --out <file.csv> [--param k=v]... [--max-age S]
# ---
exec python3 "${0:A:h:h:h:h}/lib/redash.py" "$@"
