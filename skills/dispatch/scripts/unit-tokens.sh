#!/bin/zsh
# ---
# name: unit-tokens
# description: The lead's writer for its own unit workspace's tokens — `stage`, `stories`, `prs` (never unit, kind, project). The workspace is the caller's (HERDR_PANE_ID). --stories / --prs replace the list; --add-story / --add-pr append, de-duplicated. Prints the resulting tokens.
# usage: unit-tokens.sh [--stage <stage>] [--stories a,b] [--prs o/r#1,…] [--add-story sc-#] [--add-pr o/r#n]
# ---
exec python3 "${0:A:h:h:h:h}/lib/units.py" tokens "$@"
