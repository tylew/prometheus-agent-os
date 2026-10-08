#!/bin/zsh
# ---
# name: fold
# description: Fold running units of the older kinds into epic units, one epic at a time with the operator watching — `fold.sh plan` shows the grouping, `fold.sh run --epic <id>` collects each old PM's handoff into the epic file, opens or reuses the epic unit, closes the old units once idle.
# usage: fold.sh plan [--json] | fold.sh run --epic <id> [--wait <s>]
# ---
exec python3 "${0:A:h:h:h:h}/lib/fold.py" "$@"
