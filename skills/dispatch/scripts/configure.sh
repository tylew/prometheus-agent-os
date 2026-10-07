#!/bin/zsh
# ---
# name: configure
# description: The seat's only way to change prometheus itself — open a `config-<slug>` configurator tab beside the seat with a brief holding the issue and its evidence. Refuses unless the caller is the seat.
# usage: configure.sh <slug> "<the issue, its evidence, and whether the operator already signed off>"
# ---
set -euo pipefail
[[ ${PROMETHEUS_ROLE:-} == seat ]] || { echo "configure: only the seat opens a configurator (this is ${PROMETHEUS_ROLE:-not a prometheus agent})" >&2; exit 3; }
[[ -n ${HERDR_WORKSPACE_ID:-} ]] || { echo "configure: not inside Herdr" >&2; exit 2; }
slug=${1:?usage: configure.sh <slug> <issue>}; shift
exec python3 "${0:A:h:h:h:h}/lib/units.py" configure "$HERDR_WORKSPACE_ID" "$slug" "$@"
