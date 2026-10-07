#!/usr/bin/env python3
"""Stateful stand-in for the herdr CLI in tests. World lives in $FAKE_HERDR_WORLD (JSON); every call is
appended to world["calls"]. Covers the subset prometheus uses."""
import json
import os
import sys

path = os.environ["FAKE_HERDR_WORLD"]
try:
    w = json.load(open(path))
except (OSError, ValueError):
    w = {}
w.setdefault("workspaces", []); w.setdefault("panes", []); w.setdefault("tabs", []); w.setdefault("calls", [])
w.setdefault("seq", 0)
a = sys.argv[1:]
w["calls"].append(a)
res = {}


def opt(name, default=None):
    return a[a.index(name) + 1] if name in a else default


def new_id(prefix):
    w["seq"] += 1
    return "%s%d" % (prefix, w["seq"])


def find(kind, key, val):
    return next((x for x in w[kind] if x.get(key) == val), None)


def tokens(item):
    toks = item.setdefault("tokens", {})
    i = 0
    while i < len(a):
        if a[i] == "--token":
            k, v = a[i + 1].split("=", 1)
            toks[k] = v
            i += 2
        elif a[i] == "--clear-token":
            toks.pop(a[i + 1], None)
            i += 2
        else:
            i += 1


cmd = a[:2]
if cmd == ["api", "snapshot"]:
    res = {"snapshot": {k: w[k] for k in ("workspaces", "panes", "tabs")}}
elif cmd == ["workspace", "create"]:
    ws = new_id("w")
    tab, pane = ws + ":t1", ws + ":p1"
    w["workspaces"].append({"workspace_id": ws, "label": opt("--label")})
    w["tabs"].append({"tab_id": tab, "workspace_id": ws, "label": "1"})
    w["panes"].append({"pane_id": pane, "tab_id": tab, "workspace_id": ws, "agent_status": "unknown"})
    res = {"workspace": {"workspace_id": ws}}
elif cmd == ["workspace", "get"]:
    res = {"workspace": find("workspaces", "workspace_id", a[2]) or {}}
elif cmd == ["workspace", "report-metadata"]:
    tokens(find("workspaces", "workspace_id", a[2]))
elif cmd == ["pane", "report-metadata"]:
    tokens(find("panes", "pane_id", a[2]))
elif cmd == ["workspace", "close"]:
    w["workspaces"] = [x for x in w["workspaces"] if x["workspace_id"] != a[2]]
    w["panes"] = [x for x in w["panes"] if x["workspace_id"] != a[2]]
elif cmd == ["pane", "list"]:
    res = {"panes": [p for p in w["panes"] if p["workspace_id"] == opt("--workspace")]}
elif cmd == ["tab", "create"]:
    ws = opt("--workspace")
    tab = "%s:t%d" % (ws, w["seq"] + 100); pane = "%s:p%d" % (ws, w["seq"] + 100); w["seq"] += 1
    w["tabs"].append({"tab_id": tab, "workspace_id": ws, "label": opt("--label")})
    w["panes"].append({"pane_id": pane, "tab_id": tab, "workspace_id": ws, "agent_status": "unknown"})
    res = {"tab": {"tab_id": tab}}
elif cmd == ["tab", "rename"]:
    find("tabs", "tab_id", a[2])["label"] = a[3]
elif cmd == ["tab", "list"]:
    res = {"tabs": [t for t in w["tabs"] if t["workspace_id"] == opt("--workspace")]}
elif cmd == ["tab", "close"]:
    w["tabs"] = [t for t in w["tabs"] if t["tab_id"] != a[2]]
    w["panes"] = [p for p in w["panes"] if p["tab_id"] != a[2]]
elif cmd == ["pane", "run"]:
    p = find("panes", "pane_id", a[2])
    p["agent_status"] = os.environ.get("FAKE_HERDR_LAUNCH_STATE", "idle")
    p["ran"] = a[3]
elif cmd == ["agent", "prompt"]:
    p = find("panes", "pane_id", a[2])
    p.setdefault("prompts", []).append(a[3])
    p["agent_status"] = "working"
json.dump(w, open(path, "w"))
print(json.dumps({"result": res}))
