#!/bin/zsh
# ---
# name: map
# description: The prometheus map — the primary view: header stats, the seat over every unit workspace (activity stats per unit), drill into a unit for its PM and agents, live preview of the selected agent with an interact mode that types into it. Runs in this pane; --unit opens at one unit; --split opens it without the preview in a ~32-column pane right of the caller (PROMETHEUS_MAP_WIDTH overrides); --dump prints every level as text.
# usage: map.sh [--unit <workspace_id>] [--split | --dump | --no-preview]
# ---
exec python3 "${0:A:h:h:h:h}/lib/map" "$@"
