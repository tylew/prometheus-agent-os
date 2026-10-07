#!/bin/zsh
# ---
# name: restore
# description: Bring back units a Herdr restart took — from the dispatcher's restore image, recreate each unit's workspace and tokens and resume every agent tab from its Claude session; tell the seat who came back and who had no session. --list shows what is pending; --forget <unit> drops a unit's image (closed on purpose).
# usage: restore.sh [--list] [--unit <name>]... [--forget <name>]...
# ---
exec python3 "${0:A:h:h:h:h}/lib/units.py" restore "$@"
