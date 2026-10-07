#!/bin/zsh
# ---
# name: launch
# description: The one launch recipe for every prometheus role. Merges templates/settings/launch.json with the role's allow-list (plus PROMETHEUS_EXTRA_ALLOW, one rule per line) into one settings file, adds --permission-mode dontAsk for depth-3 roles and the librarian, and execs claude with the role's agent (WORKSPACE, PROMETHEUS_ROLE set). --args prints the claude arguments as a JSON array instead, for `herdr agent start`; PROMETHEUS_DRY_RUN=1 prints the command.
# usage: launch.sh <seat|librarian|runner|planner|pm|implementor|reviewer> [--args] [extra claude args...]
# ---
set -euo pipefail

role=${1:-}
[[ -n $role ]] || { echo "usage: launch.sh <seat|librarian|planner|pm|implementor|reviewer> [--args] [claude args...]" >&2; exit 2; }
shift
args_only=0
if [[ ${1:-} == --args ]]; then args_only=1; shift; fi

case $role in
  seat)        agent=orchestrator ;;
  pm)          agent=project-manager ;;
  librarian|runner|planner|implementor|reviewer) agent=$role ;;
  *) echo "launch: unknown role '$role'" >&2; exit 2 ;;
esac

plugin_root=${0:A:h:h}
workspace=$(python3 "$plugin_root/lib/env.py") || { echo "launch: workspace root not found" >&2; exit 1; }

state_dir=${PROMETHEUS_STATE_DIR:-$HOME/.local/state/prometheus}
settings_dir=$state_dir/settings
mkdir -p "$settings_dir"
settings=$settings_dir/$role.json

WORKSPACE=$workspace python3 - "$plugin_root/templates/settings/launch.json" "$plugin_root/templates/settings/$role.json" "$settings" <<'PY'
import json, os, sys
base_path, role_path, out = sys.argv[1:4]
merged = json.load(open(base_path))
if os.path.exists(role_path):
    role = json.load(open(role_path))
    for key, val in role.items():
        if key == "$comment":
            continue
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            base = merged[key]
            merged[key] = {**base, **val}
            for k, v in val.items():  # permission lists add up; the role never drops a base rule
                if isinstance(v, list) and isinstance(base.get(k), list):
                    merged[key][k] = list(dict.fromkeys(base[k] + v))
        else:
            merged[key] = val
merged.pop("$comment", None)
state = os.environ.get("PROMETHEUS_STATE_DIR") or os.path.expanduser("~/.local/state/prometheus")
perms = merged.get("permissions") or {}
workspace = os.environ.get("WORKSPACE") or ""
for key in ("allow", "deny", "additionalDirectories"):
    if key in perms:
        perms[key] = [r.replace("{state_dir}", state).replace("{workspace}", workspace) for r in perms[key]]
extra = [r for r in os.environ.get("PROMETHEUS_EXTRA_ALLOW", "").splitlines() if r.strip()]
if extra:
    perms = merged.setdefault("permissions", {})
    perms["allow"] = list(dict.fromkeys(perms.get("allow", []) + extra))
with open(out + ".tmp", "w") as fh:
    json.dump(merged, fh, indent=2)
os.replace(out + ".tmp", out)
PY

cmd=(claude --plugin-dir "$plugin_root" --settings "$settings" --agent "prometheus:$agent")
case $role in
  implementor|reviewer|librarian) cmd+=(--permission-mode dontAsk) ;;
esac
cmd+=("$@")
if (( args_only )); then
  python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "${cmd[@]:1}"
  exit 0
fi

export WORKSPACE=$workspace PROMETHEUS_ROLE=$role
if [[ ${PROMETHEUS_DRY_RUN:-} == 1 ]]; then
  print -r -- "cd ${(q)workspace} && WORKSPACE=${(q)workspace} PROMETHEUS_ROLE=$role" ${(q)cmd[@]}
  exit 0
fi
cd "$workspace"
exec "${cmd[@]}"
