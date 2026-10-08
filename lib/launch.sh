#!/bin/zsh
# ---
# name: launch
# description: The one launch recipe for every prometheus role. Merges templates/settings/launch.json with the role's allow-list (after any base it "extends", e.g. delivery.json; {state_dir} = the realpath, named in the role prompt) (plus PROMETHEUS_EXTRA_ALLOW, one rule per line) into one settings file, adds --permission-mode dontAsk for depth-3 roles and the librarian, and execs claude with the role's agent (WORKSPACE, PROMETHEUS_ROLE set). --args prints the claude arguments as a JSON array instead, for `herdr agent start`; PROMETHEUS_DRY_RUN=1 prints the command.
# usage: launch.sh <seat|librarian|runner|configurator|planner|pm|implementor|reviewer> [--args] [extra claude args...]
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
  librarian|runner|configurator|planner|implementor|reviewer) agent=$role ;;
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
layers = []
if os.path.exists(role_path):
    role = json.load(open(role_path))
    # a role file may extend shared bases in templates/settings (e.g. delivery.json), merged before it
    layers = [json.load(open(os.path.join(os.path.dirname(role_path), b + ".json"))) for b in role.get("extends", [])]
    layers.append(role)
for layer in layers:
    for key, val in layer.items():
        if key in ("$comment", "extends"):
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
# realpath: Claude Code never matches a path rule spelled through a symlink
state = os.path.realpath(os.environ.get("PROMETHEUS_STATE_DIR") or os.path.expanduser("~/.local/state/prometheus"))
perms = merged.get("permissions") or {}
workspace = os.environ.get("WORKSPACE") or ""
role_name = os.path.basename(out)[:-5]
# per-role MCP: generated config (secrets stay out of the repo) + read/write tool rules
mcp_map = json.load(open(os.path.join(os.path.dirname(base_path), "..", "mcp", "roles.json")))
servers = {}
for src in mcp_map["sources"]:
    try:
        defs = json.load(open(os.path.join(workspace, src)))["mcpServers"]
    except (OSError, ValueError, KeyError):
        continue
    base = os.path.dirname(os.path.join(workspace, src))
    for k, v in defs.items():
        if k in servers:
            continue
        if v.get("args"):  # sub-repo stdio servers name paths relative to their repo: make them absolute
            v = dict(v, args=[os.path.join(base, x) if not x.startswith(("-", "/", ":")) and
                              os.path.exists(os.path.join(base, x)) and base != workspace else x for x in v["args"]])
        servers[k] = v
mine = [s for s in mcp_map["roles"].get(role_name, []) if s in servers]
mcp_dir = os.path.join(state, "mcp")
os.makedirs(mcp_dir, exist_ok=True)
mcp_path = os.path.join(mcp_dir, role_name + ".json")
fd = os.open(mcp_path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as fh:
    json.dump({"mcpServers": {s: servers[s] for s in mine}}, fh, indent=2)
os.replace(mcp_path + ".tmp", mcp_path)
mperms = merged.setdefault("permissions", {})
mperms["allow"] = list(dict.fromkeys(mperms.get("allow", []) + ["mcp__%s" % s for s in mine]))
deny = [("mcp__%s__%s" % (s, t)) for s in mine for t in mcp_map["write_tools"].get(s, [])
        if role_name not in mcp_map["writers"].get(s, [])]
mperms["deny"] = list(dict.fromkeys(mperms.get("deny", []) + deny))
for tool, spec in mcp_map.get("cli", {}).items():
    if role_name in spec.get("roles", []):
        for kind in ("allow", "ask", "deny"):
            mperms[kind] = list(dict.fromkeys(mperms.get(kind, []) + ["Bash(%s)" % c for c in spec.get(kind, [])]))
    else:
        mperms["deny"] = list(dict.fromkeys(mperms.get("deny", []) + ["Bash(%s *)" % tool]))
ask = [("mcp__%s__%s" % (s, t)) for s in mine if role_name in mcp_map.get("ask_writers", {}).get(s, [])
       for t in mcp_map["write_tools"].get(s, [])]
if ask:  # a writer that still asks the operator per call (ask beats allow)
    mperms["ask"] = list(dict.fromkeys(mperms.get("ask", []) + ask))
# operator awareness + signature, appended to the system prompt; the registry is the one home of both
LEADS = {"implementor": "your PM (`send.sh --role pm`)", "reviewer": "your PM (`send.sh --role pm`)",
         "planner": "your PM (`send.sh --role pm`)", "runner": "the seat (`send.sh --role seat`)",
         "librarian": "the seat (`send.sh --role seat`)", "configurator": "the seat (`send.sh --role seat`)"}
op = {}
try:
    sys.path.insert(0, os.path.join(os.path.dirname(base_path), "..", "..", "lib"))
    import registry
    op = (registry.workspace_config(workspace) or {}).get("operator") or {}
except Exception:  # noqa: BLE001 — no registry: the prompt still carries hierarchy + a generic signature
    pass
vals = {"name": op.get("name", "the operator"), "full_name": op.get("full_name", op.get("name", "")),
        "github": op.get("github", op.get("codeowners_handle", "")).lstrip("@"),
        "lead": LEADS.get(role_name, "the seat")}
vals["signature"] = (op.get("signature") or "⚡ Prometheus by instruction of {name}").format(**vals)
tmpl = open(os.path.join(os.path.dirname(base_path), "..", "operator.md")).read().split("---", 2)[2]
sections = {}
for chunk in tmpl.split("<!-- ")[1:]:
    head, body = chunk.split(" -->", 1)
    sections[head.split(":")[0].strip()] = body.strip()
keep = ["operator" if role_name in ("seat", "pm") else "hierarchy", "signature"]
with open(os.path.join(state, "settings", role_name + ".prompt.md"), "w") as fh:
    fh.write("\n\n".join(sections[k].format(**vals) for k in keep) + "\n")
    fh.write("\nPrometheus state dir: `%s` — `<state_dir>` in skills and briefs means this path.\n" % state)
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

cmd=(claude --plugin-dir "$plugin_root" --settings "$settings" --agent "prometheus:$agent"
     --mcp-config "$state_dir/mcp/$role.json" --strict-mcp-config
     --append-system-prompt-file "$settings_dir/$role.prompt.md")
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
