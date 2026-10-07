#!/usr/bin/env python3
# ---
# name: units
# description: Unit workspaces and agent tabs over Herdr — create a unit (workspace, tokens, lead tab), list and close units, open / brief / close agent tabs (role tokens, launch.sh, allow-list extras), and context hygiene (compact an idle agent, refresh a session in a new tab). The unit-workspaces, agent-tabs and context-hygiene scripts are thin wrappers over its subcommands.
# usage: units.py {create|list|close|open-tab|send-brief|close-tab|compact|refresh} [args]
# ---
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import time

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import dispatch  # noqa: E402
import env  # noqa: E402

KINDS = ("story", "story-set", "planning", "goal-set", "review")
ROLES = ("pm", "planner", "implementor", "reviewer")
READY_STATES = ("idle", "done")
BUSY_STATES = ("working", "blocked")


def _h(*args: str) -> dict:
    return dispatch.herdr(*args)


def _snap() -> dict:
    return dispatch.snapshot()


def _tokens(item: dict | None) -> dict:
    return (item or {}).get("tokens") or {}


def _status(pane_id: str) -> str:
    p = dispatch.pane(_snap(), pane_id)
    return (p or {}).get("agent_status", "gone")


def _first_pane(workspace_id: str, tab_id: str | None = None) -> str:
    panes = _h("pane", "list", "--workspace", workspace_id).get("panes", [])
    for p in panes:
        if tab_id is None or p.get("tab_id") == tab_id:
            return p["pane_id"]
    raise RuntimeError("no pane in %s %s" % (workspace_id, tab_id or ""))


def tag_workspace(workspace_id: str, **tokens: str) -> None:
    args = ["workspace", "report-metadata", workspace_id, "--source", "prometheus"]
    for k, v in tokens.items():
        if v is None:
            continue
        args += ["--token", "%s=%s" % (k, v)]
    _h(*args)


def tag_pane(pane_id: str, **tokens: str) -> None:
    args = ["pane", "report-metadata", pane_id, "--source", "prometheus"]
    for k, v in tokens.items():
        if v:
            args += ["--token", "%s=%s" % (k, v)]
    _h(*args)


def _launch_cmd(role: str, extra_allow: list[str] | None = None, claude_args: list[str] | None = None) -> str:
    plugin = os.path.dirname(LIB)
    parts = []
    for var in ("PROMETHEUS_STATE_DIR", "PROMETHEUS_FILTER"):
        if os.environ.get(var):
            parts.append("%s=%s" % (var, shlex.quote(os.environ[var])))
    if extra_allow:
        parts.append("PROMETHEUS_EXTRA_ALLOW=%s" % shlex.quote("\n".join(extra_allow)))
    parts.append(shlex.quote(os.path.join(plugin, "lib", "launch.sh")))
    parts.append(role)
    parts += [shlex.quote(a) for a in (claude_args or [])]
    return " ".join(parts)


def _wait_ready(pane_id: str, timeout: float = 90) -> str:
    """Wait until a freshly launched agent sits at its prompt (idle / done)."""
    deadline = time.time() + timeout
    st = "unknown"
    while time.time() < deadline:
        st = _status(pane_id)
        if st in READY_STATES:
            return st
        time.sleep(1)
    return st


# ------------------------------------------------------------------- units

def create(name: str, kind: str, project: str, stories: list[str], prs: list[str],
           brief: str | None = None, claude_args: list[str] | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError("kind must be one of %s" % ", ".join(KINDS))
    if any(dispatch._tokens(u).get("unit") == name for u in dispatch.units(_snap())):
        raise ValueError("unit %s already exists" % name)
    if kind == "planning":
        return _create_planner(name, project, stories, brief, claude_args)
    root = env.workspace_root()
    if kind != "planning":
        handoff(stories)
    ws = _h("workspace", "create", "--label", name, "--cwd", root, "--no-focus")
    ws_id = (ws.get("workspace") or ws)["workspace_id"]
    lead = "planner" if kind == "planning" else "pm"
    tag_workspace(ws_id, unit=name, kind=kind, project=project,
                  stories=",".join(stories) or None, prs=",".join(prs) or None,
                  stage="planning" if kind == "planning" else "triage")
    pane_id = _first_pane(ws_id)
    tab_id = pane_id.split(":")[0] + ":" + "t1"
    for p in _h("pane", "list", "--workspace", ws_id).get("panes", []):
        if p["pane_id"] == pane_id:
            tab_id = p.get("tab_id", tab_id)
    _h("tab", "rename", tab_id, lead)
    tag_pane(pane_id, role=lead)
    _h("pane", "run", pane_id, _launch_cmd(lead, claude_args=claude_args))
    out = {"workspace": ws_id, "unit": name, "lead": lead, "pane": pane_id}
    if brief:
        out["brief"] = send_brief(pane_id, brief)
    return out


def control_workspace() -> str:
    """The seat's workspace — where planners live beside the seat and the dispatcher."""
    seats = dispatch.panes_with_role(_snap(), "seat")
    ws = seats[0]["workspace_id"] if seats else os.environ.get("HERDR_WORKSPACE_ID")
    if not ws:
        raise RuntimeError("no seat pane and no HERDR_WORKSPACE_ID: cannot find the control workspace")
    return ws


def _create_planner(name: str, project: str, stories: list[str], brief: str | None, claude_args) -> dict:
    """A planning unit is a tab in the control workspace; its tokens live on the planner's pane."""
    ws = control_workspace()
    tab = _h("tab", "create", "--workspace", ws, "--label", name, "--cwd", env.workspace_root(), "--no-focus")
    tab_id = (tab.get("tab") or tab)["tab_id"]
    pane_id = _first_pane(ws, tab_id)
    tag_pane(pane_id, role="planner", unit=name, kind="planning", project=project,
             stories=",".join(stories) or None, stage="planning")
    _h("pane", "run", pane_id, _launch_cmd("planner", claude_args=claude_args))
    out = {"workspace": ws, "unit": name, "lead": "planner", "pane": pane_id}
    if brief:
        out["brief"] = send_brief(pane_id, brief)
    return out


def tag_unit(unit: dict, **tokens: str) -> None:
    """Write unit tokens wherever the unit lives: its pane (planner tab) or its workspace."""
    if unit.get("pane_id"):
        tag_pane(unit["pane_id"], **tokens)
    else:
        tag_workspace(unit["workspace_id"], **tokens)


def handoff(stories: list[str]) -> list[str]:
    """A story moving into a delivery unit leaves every planning unit, so its events have one owner."""
    moved = []
    for u in dispatch.units(_snap()):
        t = dispatch._tokens(u)
        if t.get("kind") != "planning":
            continue
        held = dispatch._csv(t.get("stories"))
        keep = [s for s in held if s not in stories]
        if keep != held:
            where = ["pane", "report-metadata", u["pane_id"]] if u.get("pane_id") else \
                ["workspace", "report-metadata", u["workspace_id"]]
            args = where + ["--source", "prometheus"]
            args += ["--token", "stories=%s" % ",".join(keep)] if keep else ["--clear-token", "stories"]
            _h(*args)
            moved += [s for s in held if s in stories]
    return moved


def list_units() -> list[dict]:
    snap = _snap()
    rows = []
    for u in dispatch.units(snap):
        t = dispatch._tokens(u)
        lead = dispatch.lead_role(u)
        leads = [dispatch.pane(snap, u["pane_id"])] if u.get("pane_id") else \
            dispatch.panes_with_role(snap, lead, u["workspace_id"])
        rows.append({"workspace": u.get("pane_id") or u["workspace_id"], "unit": t.get("unit"), "kind": t.get("kind"),
                     "project": t.get("project"), "stage": t.get("stage"),
                     "stories": t.get("stories"), "prs": t.get("prs"),
                     "lead": lead, "lead_status": leads[0].get("agent_status") if leads else "missing"})
    return rows


def close(workspace_id: str, force: bool = False) -> None:
    """Close a unit by workspace id, or a planning unit by its pane id or label."""
    snap = _snap()
    planner = next((u for u in dispatch.units(snap) if u.get("pane_id")
                    and workspace_id in (u["pane_id"], dispatch._tokens(u).get("unit"))), None)
    if planner:
        p = dispatch.pane(snap, planner["pane_id"])
        if p and p.get("agent_status") in BUSY_STATES and not force:
            raise ValueError("planner %s is %s" % (planner["pane_id"], p.get("agent_status")))
        _h("tab", "close", p["tab_id"])
        return
    unit = dispatch.unit_of_workspace(snap, workspace_id)
    if not unit:
        raise ValueError("%s carries no prometheus unit token; refusing" % workspace_id)
    busy = [p["pane_id"] for p in snap.get("panes", [])
            if p.get("workspace_id") == workspace_id and _tokens(p).get("role")
            and p.get("agent_status") in BUSY_STATES]
    if busy and not force:
        raise ValueError("agents still working or blocked: %s" % ", ".join(busy))
    _h("workspace", "close", workspace_id)


# -------------------------------------------------------------------- tabs

def open_tab(workspace_id: str, label: str, role: str, item: str | None = None,
             pr: str | None = None, worktree: str | None = None,
             extra_allow: list[str] | None = None, claude_args: list[str] | None = None) -> str:
    if role not in ROLES:
        raise ValueError("role must be one of %s" % ", ".join(ROLES))
    tab = _h("tab", "create", "--workspace", workspace_id, "--label", label,
             "--cwd", env.workspace_root(), "--no-focus")
    tab_id = (tab.get("tab") or tab)["tab_id"]
    pane_id = _first_pane(workspace_id, tab_id)
    tag_pane(pane_id, role=role, item=item, pr=pr, worktree=worktree)
    _h("pane", "run", pane_id, _launch_cmd(role, extra_allow, claude_args))
    return pane_id


def send_brief(pane_id: str, brief_path: str, ready_timeout: float = 90, landed_timeout: float = 20) -> str:
    """Prompt one line pointing at the brief; confirm it landed by state. Never re-sends."""
    if not os.path.isfile(brief_path):
        raise ValueError("brief not found: %s" % brief_path)
    st = _wait_ready(pane_id, ready_timeout)
    if st not in READY_STATES:
        raise RuntimeError("agent in %s never reached its prompt (last: %s)" % (pane_id, st))
    result = dispatch.submit(pane_id, "Read your brief at %s and begin." % os.path.abspath(brief_path),
                             wait=landed_timeout / 2)
    st = _status(pane_id)
    if st in BUSY_STATES:
        return "landed (%s)" % st
    raise RuntimeError("brief prompt not observed landing in %s (%s, state %s); not re-sending" % (pane_id, result, st))


def _tab_by_label(workspace_id: str, label: str) -> str | None:
    tabs = _h("tab", "list", "--workspace", workspace_id).get("tabs", [])
    return next((t["tab_id"] for t in tabs if t.get("label") == label), None)


def close_tab(workspace_id: str, label: str) -> None:
    tab_id = _tab_by_label(workspace_id, label)
    if not tab_id:
        raise ValueError("no tab %s in %s" % (label, workspace_id))
    _h("tab", "close", tab_id)


# --------------------------------------------------------- context hygiene

def compact(pane_id: str, focus: str) -> None:
    st = _status(pane_id)
    if st not in READY_STATES:
        raise ValueError("agent %s is %s; /compact only at its prompt" % (pane_id, st))
    _h("agent", "prompt", pane_id, "/compact %s" % focus)


def refresh(workspace_id: str, label: str, role: str, brief: str, **tab_tokens) -> str:
    if _tab_by_label(workspace_id, label):
        close_tab(workspace_id, label)
    pane_id = open_tab(workspace_id, label, role, **tab_tokens)
    send_brief(pane_id, brief)
    return pane_id


# --------------------------------------------------------------------- CLI

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="units.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("name")
    c.add_argument("kind", choices=KINDS)
    c.add_argument("project")
    c.add_argument("--stories", default="")
    c.add_argument("--prs", default="")
    c.add_argument("--brief")
    sub.add_parser("list").add_argument("--json", action="store_true")
    cl = sub.add_parser("close")
    cl.add_argument("workspace")
    cl.add_argument("--force", action="store_true")
    o = sub.add_parser("open-tab")
    o.add_argument("workspace")
    o.add_argument("label")
    o.add_argument("role", choices=ROLES)
    o.add_argument("--item")
    o.add_argument("--pr")
    o.add_argument("--worktree")
    o.add_argument("--allow", action="append", default=[], help="extra allow rule; repeatable")
    b = sub.add_parser("send-brief")
    b.add_argument("pane")
    b.add_argument("brief")
    ct = sub.add_parser("close-tab")
    ct.add_argument("workspace")
    ct.add_argument("label")
    cp = sub.add_parser("compact")
    cp.add_argument("pane")
    cp.add_argument("focus", nargs="+")
    r = sub.add_parser("refresh")
    r.add_argument("workspace")
    r.add_argument("label")
    r.add_argument("role", choices=ROLES)
    r.add_argument("brief")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "create":
            print(json.dumps(create(a.name, a.kind, a.project, dispatch._csv(a.stories),
                                    dispatch._csv(a.prs), a.brief)))
        elif a.cmd == "list":
            rows = list_units()
            if a.json:
                print(json.dumps(rows))
            else:
                for r_ in rows:
                    print("{unit}\t{kind}\t{stage}\t{lead}:{lead_status}\t{workspace}".format(**r_))
        elif a.cmd == "close":
            close(a.workspace, a.force)
            print("closed %s" % a.workspace)
        elif a.cmd == "open-tab":
            print(open_tab(a.workspace, a.label, a.role, a.item, a.pr, a.worktree, a.allow))
        elif a.cmd == "send-brief":
            print(send_brief(a.pane, a.brief))
        elif a.cmd == "close-tab":
            close_tab(a.workspace, a.label)
            print("closed %s" % a.label)
        elif a.cmd == "compact":
            compact(a.pane, " ".join(a.focus))
            print("compact sent to %s" % a.pane)
        elif a.cmd == "refresh":
            print(refresh(a.workspace, a.label, a.role, a.brief))
    except (ValueError, RuntimeError) as exc:
        print("units: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
