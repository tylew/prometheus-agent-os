#!/bin/zsh
# ---
# name: launch
# description: The one launch line for every prometheus role. Resolves WORKSPACE, sets PROMETHEUS_ROLE, merges templates/settings/launch.json with the role's allow-list (plus PROMETHEUS_EXTRA_ALLOW, one rule per line) into one settings file, adds --permission-mode dontAsk for depth-3 roles, and execs claude with the role's agent. PROMETHEUS_DRY_RUN=1 prints the command instead.
# usage: launch.sh <seat|planner|pm|implementor|reviewer> [extra claude args...]
# ---
set -euo pipefail

role=${1:-}
[[ -n $role ]] || { echo "usage: launch.sh <seat|planner|pm|implementor|reviewer> [claude args...]" >&2; exit 2; }
shift

case $role in
  seat)        agent=orchestrator ;;
  pm)          agent=project-manager ;;
  planner|implementor|reviewer) agent=$role ;;
  *) echo "launch: unknown role '$role'" >&2; exit 2 ;;
esac

plugin_root=${0:A:h:h}
workspace=$(python3 "$plugin_root/lib/env.py") || { echo "launch: workspace root not found" >&2; exit 1; }

state_dir=${PROMETHEUS_STATE_DIR:-$HOME/.claude/prometheus}
settings_dir=$state_dir/settings
mkdir -p "$settings_dir"
settings=$settings_dir/$role.json

python3 - "$plugin_root/templates/settings/launch.json" "$plugin_root/templates/settings/$role.json" "$settings" <<'PY'
import json, os, sys
base_path, role_path, out = sys.argv[1:4]
merged = json.load(open(base_path))
if os.path.exists(role_path):
    role = json.load(open(role_path))
    for key, val in role.items():
        if key == "$comment":
            continue
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **val}
        else:
            merged[key] = val
merged.pop("$comment", None)
state = os.environ.get("PROMETHEUS_STATE_DIR") or os.path.expanduser("~/.claude/prometheus")
perms = merged.get("permissions") or {}
for key in ("allow", "deny"):
    if key in perms:
        perms[key] = [r.replace("{state_dir}", state) for r in perms[key]]
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
  implementor|reviewer) cmd+=(--permission-mode dontAsk) ;;
esac
cmd+=("$@")

export WORKSPACE=$workspace PROMETHEUS_ROLE=$role
if [[ ${PROMETHEUS_DRY_RUN:-} == 1 ]]; then
  print -r -- "cd ${(q)workspace} && WORKSPACE=${(q)workspace} PROMETHEUS_ROLE=$role" ${(q)cmd[@]}
  exit 0
fi
cd "$workspace"
exec "${cmd[@]}"
