#!/bin/zsh
# ---
# name: map
# description: The prometheus map — an interactive tree of seat, dispatcher, librarian and every unit's PM and workers (status, needs-you flags, held outbox, proposals, activity). Runs in this pane; --split opens it in a ~32-column pane right of the caller (PROMETHEUS_MAP_WIDTH overrides); --unit scopes it to one unit workspace; --dump prints the tree as text.
# usage: map.sh [--unit <workspace_id>] [--split | --dump]
# ---
exec python3 "${0:A:h:h:h:h}/lib/map" "$@"
