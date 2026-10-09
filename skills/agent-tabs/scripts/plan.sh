#!/bin/zsh
# ---
# name: plan
# description: Open one planner per issue in the caller's unit workspace — `plan-sc-<id>` takes that story to Ready, `plan-<slug>` turns a new issue into stories (discovery) — with its brief written and sent, the way the seat opens `config-<slug>`. Refuses a label already open (message that planner with send.sh --role planner --item <item>). PM or seat only.
# usage: plan.sh <sc-<id> | slug naming the issue> [--context <file>]... "<the ask, the operator's words verbatim where you have them>"
# ---
set -euo pipefail
[[ ${PROMETHEUS_ROLE:-} == (pm|seat) ]] || { echo "plan: only a PM or the seat opens a planner (this is ${PROMETHEUS_ROLE:-not a prometheus agent})" >&2; exit 3; }
[[ -n ${HERDR_WORKSPACE_ID:-} ]] || { echo "plan: not inside Herdr" >&2; exit 2; }
item=${1:?usage: plan.sh <sc-<id>|slug> [--context <file>]... <ask>}; shift
exec python3 "${0:A:h:h:h:h}/lib/units.py" plan "$HERDR_WORKSPACE_ID" "$item" "$@"
