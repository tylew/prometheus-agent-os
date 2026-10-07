# ---
# name: map
# description: The prometheus map — the operator's primary curses view: the seat over every unit workspace, drill-down into a unit's PM and agents, live preview of the selected agent with an interact mode, built from prometheus Herdr tokens plus a read-only dispatch.json overlay. Canvas and edge animation ported from Horchestra's agent map.
# usage: python3 -m map (from lib/) | python3 lib/map [--unit <workspace_id>] [--dump | --split | --no-preview] | skills/dispatch/scripts/map.sh
# ---
# Ported from Horchestra (https://github.com/SimoneDaniotti/horchestra),
# MIT License, Copyright (c) 2026 Simone Daniotti.
