#!/bin/zsh
# ---
# name: begin
# description: Start the OS from the seat — require Herdr, refuse a second dispatcher, open a `dispatcher` tab in the seat's own (control) workspace running dispatcher.sh, and print the status. Used by /prometheus:begin.
# usage: [INTERVAL=<s>] [HEARTBEAT=<min>] begin.sh
# ---
set -euo pipefail
[[ ${HERDR_ENV:-} == 1 && -n ${HERDR_WORKSPACE_ID:-} ]] || { echo "begin: not inside Herdr" >&2; exit 2; }
here=${0:A:h}
lib=${0:A:h:h:h:h}/lib
if python3 "$lib/dispatch.py" status >/dev/null; then
  echo "begin: dispatcher already $(python3 "$lib/dispatch.py" status)"
  exit 0
fi
workspace=$(python3 "$lib/env.py")
tab=$(herdr tab create --workspace "$HERDR_WORKSPACE_ID" --label dispatcher --cwd "$workspace" --no-focus \
      | python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; print((r.get("tab") or r)["tab_id"])')
pane=$(herdr pane list --workspace "$HERDR_WORKSPACE_ID" \
      | python3 -c 'import json,sys; t=sys.argv[1]; print(next(p["pane_id"] for p in json.load(sys.stdin)["result"]["panes"] if p["tab_id"]==t))' "$tab")
state=${PROMETHEUS_STATE_DIR:+PROMETHEUS_STATE_DIR=${(q)PROMETHEUS_STATE_DIR} }
state+=${PROMETHEUS_FILTER:+PROMETHEUS_FILTER=${(q)PROMETHEUS_FILTER} }
herdr pane run "$pane" "${state}HERDR_WORKSPACE_ID=$HERDR_WORKSPACE_ID INTERVAL=${INTERVAL:-60} HEARTBEAT=${HEARTBEAT:-30} ${(q)here}/dispatcher.sh" >/dev/null
for _ in {1..20}; do python3 "$lib/dispatch.py" status >/dev/null && break; sleep 0.5; done
echo "begin: dispatcher $(python3 "$lib/dispatch.py" status) in tab $tab (pane $pane)"
