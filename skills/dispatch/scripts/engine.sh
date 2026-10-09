#!/bin/zsh
# ---
# name: engine
# description: The unit engine's controls — its per-story stages and waits (status), switching a unit to the engine (on: shadow — it records and feeds what it sees, the PM still acts) or back (off), the duties it acts on for a unit (act <unit> review,pull,…; empty = shadow), and a unit's feed.
# usage: engine.sh status [--unit <label>] | engine.sh on|off <unit> | engine.sh act <unit> <duty,…> | engine.sh feed <unit> [-n N]
# ---
exec python3 "${0:A:h:h:h:h}/lib/unit_engine.py" "$@"
