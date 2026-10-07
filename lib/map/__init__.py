# ---
# name: map
# description: The prometheus map — an interactive curses tree of the seat, dispatcher, librarian and every unit's PM and workers, built from prometheus Herdr tokens plus a read-only dispatch.json overlay. Ported from Horchestra's agent map.
# usage: python3 -m map (from lib/) | python3 lib/map [--unit <workspace_id>] [--dump | --split] | skills/dispatch/scripts/map.sh
# ---
# Ported from Horchestra (https://github.com/SimoneDaniotti/horchestra),
# MIT License, Copyright (c) 2026 Simone Daniotti.
