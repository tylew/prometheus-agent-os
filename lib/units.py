#!/usr/bin/env python3
# ---
# name: units
# description: Unit workspaces and agent tabs over Herdr — create a unit (workspace, tokens, lead tab), list and close units, open / brief / close agent tabs (role tokens, `herdr agent start` with launch.sh's args, allow-list extras), the control tabs beside the seat (librarian, map), restoring units from the dispatcher's image after a Herdr restart, and context hygiene (compact an idle agent, refresh a session in a new tab). The unit-workspaces, agent-tabs and context-hygiene scripts are thin wrappers over its subcommands.
# usage: units.py {create|list|close|open-tab|send-brief|close-tab|compact|refresh|control-tabs|restore} [args]
# ---
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import dispatch  # noqa: E402
import env  # noqa: E402
import herdr as hz  # noqa: E402

KINDS = ("story", "story-set", "goal-set", "review")
ROLES = ("pm", "planner", "implementor", "reviewer", "librarian", "runner")
READY_STATES = ("idle", "done")
BUSY_STATES = ("working", "blocked")
PASS_ENV = ("PROMETHEUS_STATE_DIR", "PROMETHEUS_FILTER", "PROMETHEUS_EXTERNAL", "PROMETHEUS_KB_ROOT")


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


def _env_flags(role: str) -> list[str]:
    """Tab / workspace env for the agent's shell: role, workspace root, trial isolation."""
    skills = os.path.join(os.path.dirname(LIB), "skills")
    scripts = os.pathsep.join(os.path.join(skills, s, "scripts") for s in ("dispatch", "knowledge"))
    pairs = {"PROMETHEUS_ROLE": role, "WORKSPACE": env.workspace_root(),
             "PATH": scripts + os.pathsep + os.environ.get("PATH", "")}  # send.sh / report.sh / kb.sh, bare
    pairs.update({k: os.environ[k] for k in PASS_ENV if os.environ.get(k)})
    out = []
    for k, v in pairs.items():
        out += ["--env", "%s=%s" % (k, v)]
    return out


def launch_args(role: str, extra_allow: list[str] | None = None, claude_args: list[str] | None = None) -> list[str]:
    run_env = dict(os.environ)
    if extra_allow:
        run_env["PROMETHEUS_EXTRA_ALLOW"] = "\n".join(extra_allow)
    out = subprocess.run([os.path.join(LIB, "launch.sh"), role, "--args", *(claude_args or [])],
                         capture_output=True, text=True, env=run_env, timeout=30)
    if out.returncode != 0:
        raise RuntimeError("launch.sh %s: %s" % (role, out.stderr.strip()))
    return json.loads(out.stdout)


def herdr_name(name: str, pane_id: str) -> str:
    """Herdr agent names: a lowercase letter first, [a-z0-9_-], at most 32 chars. The pane id keeps it unique."""
    suffix = re.sub(r"[^a-z0-9]+", "-", pane_id.lower()).strip("-")
    prefix = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")[:31 - len(suffix)].rstrip("-_")
    out = ("%s-%s" % (prefix, suffix)) if prefix else suffix
    return out if out[0].isalpha() else "p" + out[:31]


def start(pane_id: str, role: str, name: str, label: str, extra_allow: list[str] | None = None,
          claude_args: list[str] | None = None) -> None:
    """Start the role's Claude in a shell pane; returns when Herdr sees it ready for input."""
    args = launch_args(role, extra_allow, ["--name", label, *(claude_args or [])])
    agent_name = herdr_name(name, pane_id)
    try:
        hz.start_agent(agent_name, pane_id, args)
    except hz.HerdrError as exc:
        if exc.code != "agent_not_ready":
            raise RuntimeError("could not start %s in %s: %s" % (role, pane_id, exc))
        # up but asking something (e.g. folder trust): the operator answers in the pane


# ------------------------------------------------------------------- units

def create(name: str, kind: str, project: str, stories: list[str], prs: list[str],
           brief: str | None = None, claude_args: list[str] | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError("kind must be one of %s" % ", ".join(KINDS))
    if any(dispatch._tokens(u).get("unit") == name for u in dispatch.units(_snap())):
        raise ValueError("unit %s already exists" % name)
    root = env.workspace_root()
    ws = _h("workspace", "create", "--label", name, "--cwd", root, "--no-focus", *_env_flags("pm"))
    ws_id = (ws.get("workspace") or ws)["workspace_id"]
    lead = "pm"
    tag_workspace(ws_id, unit=name, kind=kind, project=project,
                  stories=",".join(stories) or None, prs=",".join(prs) or None,
                  stage="triage")
    pane_id = _first_pane(ws_id)
    tab_id = pane_id.split(":")[0] + ":" + "t1"
    for p in _h("pane", "list", "--workspace", ws_id).get("panes", []):
        if p["pane_id"] == pane_id:
            tab_id = p.get("tab_id", tab_id)
    _h("tab", "rename", tab_id, lead)
    tag_pane(pane_id, role=lead)
    try:
        start(pane_id, lead, name, lead, claude_args=claude_args)
    except RuntimeError:
        _h("workspace", "close", ws_id)  # no half-made unit: the caller reports and the next tick retries
        raise
    out = {"workspace": ws_id, "unit": name, "lead": lead, "pane": pane_id}
    if brief:
        out["brief"] = send_brief(pane_id, brief)
    return out


def list_units() -> list[dict]:
    snap = _snap()
    rows = []
    for u in dispatch.units(snap):
        t = dispatch._tokens(u)
        lead = dispatch.lead_role(u)
        leads = dispatch.panes_with_role(snap, lead, u["workspace_id"])
        rows.append({"workspace": u["workspace_id"], "unit": t.get("unit"), "kind": t.get("kind"),
                     "project": t.get("project"), "stage": t.get("stage"),
                     "stories": t.get("stories"), "prs": t.get("prs"),
                     "lead": lead, "lead_status": leads[0].get("agent_status") if leads else "missing"})
    return rows


def close(workspace_id: str, force: bool = False) -> None:
    snap = _snap()
    unit = dispatch.unit_of_workspace(snap, workspace_id)
    if not unit:
        raise ValueError("%s carries no prometheus unit token; refusing" % workspace_id)
    busy = [p["pane_id"] for p in snap.get("panes", [])
            if p.get("workspace_id") == workspace_id and _tokens(p).get("role")
            and p.get("agent_status") in BUSY_STATES]
    if busy and not force:
        raise ValueError("agents still working or blocked: %s" % ", ".join(busy))
    _h("workspace", "close", workspace_id)
    with dispatch.locked_state() as st:
        st.get("image", {}).pop(unit_name(unit), None)


def unit_name(unit: dict) -> str:
    return dispatch._tokens(unit).get("unit", "")


# -------------------------------------------------------------------- tabs

def open_tab(workspace_id: str, label: str, role: str, item: str | None = None,
             pr: str | None = None, worktree: str | None = None,
             extra_allow: list[str] | None = None, claude_args: list[str] | None = None) -> str:
    if role not in ROLES:
        raise ValueError("role must be one of %s" % ", ".join(ROLES))
    # a tab with a worktree starts in it: under dontAsk its git / gt calls must not need cd or -C
    cwd = worktree if worktree and os.path.isdir(worktree) else env.workspace_root()
    tab = _h("tab", "create", "--workspace", workspace_id, "--label", label,
             "--cwd", cwd, "--no-focus", *_env_flags(role))
    tab_id = (tab.get("tab") or tab)["tab_id"]
    pane_id = _first_pane(workspace_id, tab_id)
    tag_pane(pane_id, role=role, item=item, pr=pr, worktree=worktree)
    unit = dispatch.unit_of_workspace(_snap(), workspace_id)
    start(pane_id, role, unit_name(unit) if unit else "prometheus", label, extra_allow, claude_args)
    return pane_id


def send_brief(pane_id: str, brief_path: str) -> str:
    """Prompt one line pointing at the brief; Herdr confirms a turn started (resent only on a stall)."""
    if not os.path.isfile(brief_path):
        raise ValueError("brief not found: %s" % brief_path)
    result = dispatch.submit(pane_id, "Read your brief at %s and begin." % os.path.abspath(brief_path))
    if result == "stalled":
        raise RuntimeError("brief never started a turn in %s (state %s)" % (pane_id, _status(pane_id)))
    return "landed (%s)" % result


def _tab_by_label(workspace_id: str, label: str) -> str | None:
    tabs = _h("tab", "list", "--workspace", workspace_id).get("tabs", [])
    return next((t["tab_id"] for t in tabs if t.get("label") == label), None)


def close_tab(workspace_id: str, label: str) -> None:
    tab_id = _tab_by_label(workspace_id, label)
    if not tab_id:
        raise ValueError("no tab %s in %s" % (label, workspace_id))
    _h("tab", "close", tab_id)


# ------------------------------------------------------------ control tabs

def control_tabs(workspace_id: str) -> list[str]:
    """Beside the seat: a `librarian` agent tab and a `map` tab, each opened only if missing."""
    snap = _snap()
    done = []
    if not dispatch.panes_with_role(snap, "librarian", workspace_id):
        open_tab(workspace_id, "librarian", "librarian")
        done.append("librarian")
    if not any(_tokens(p).get("view") == "map" and p.get("workspace_id") == workspace_id
               for p in snap.get("panes", [])):
        tab = _h("tab", "create", "--workspace", workspace_id, "--label", "map",
                 "--cwd", env.workspace_root(), "--no-focus", *_env_flags("map"))
        pane_id = _first_pane(workspace_id, (tab.get("tab") or tab)["tab_id"])
        _h("pane", "run", pane_id, shlex.quote(os.path.join(os.path.dirname(LIB), "skills", "dispatch",
                                                            "scripts", "map.sh")))
        done.append("map")
    return done


# -------------------------------------------------------------- quick work

def quick(workspace_id: str, slug: str, ask: str) -> dict:
    """One quick work item: a `quick-<slug>` runner tab beside the seat, its exports folder, its brief."""
    slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")
    label = "quick-%s" % slug
    if _tab_by_label(workspace_id, label):
        raise ValueError("%s is already open" % label)
    exports = os.path.join(dispatch.state_dir(), "exports", slug)
    os.makedirs(exports, exist_ok=True)
    brief = os.path.join(dispatch.state_dir(), "briefs", "%s.md" % label)
    os.makedirs(os.path.dirname(brief), exist_ok=True)
    with open(brief, "w") as fh:
        fh.write("# %s\n\n## Ask (the operator's words)\n%s\n\n## Exports folder\n%s\n\n"
                 "## Report to\nThe seat: `send.sh --role seat \"%s done: <paths> — <one line>\"`.\n"
                 % (label, ask, exports, label))
    pane_id = open_tab(workspace_id, label, "runner", item=slug)
    return {"pane": pane_id, "label": label, "exports": exports, "brief": send_brief(pane_id, brief)}


# ----------------------------------------------------------------- restore

def session_on_disk(session: str | None) -> bool:
    if not session:
        return False
    root = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"), "projects")
    return any(os.path.exists(os.path.join(root, d, session + ".jsonl"))
               for d in (os.listdir(root) if os.path.isdir(root) else []))


def restore_unit(name: str, record: dict) -> dict:
    """Recreate a unit lost to a Herdr restart: workspace, tokens, one tab per imaged agent resumed from
    its session. An agent whose session is gone is not started fresh; it is reported."""
    toks = record["tokens"]
    root = env.workspace_root()
    ws = _h("workspace", "create", "--label", name, "--cwd", root, "--no-focus", *_env_flags("pm"))
    ws_id = (ws.get("workspace") or ws)["workspace_id"]
    tag_workspace(ws_id, **toks)
    back, missing = [], []
    first = True
    for agent in record.get("agents", []):
        role, label, session = agent["tokens"].get("role"), agent["label"], agent.get("session")
        if not session_on_disk(session):
            missing.append(label)
            continue
        extra = {k: v for k, v in agent["tokens"].items() if k != "role"}
        if first:
            pane_id = _first_pane(ws_id)
            tab_id = next(p["tab_id"] for p in _h("pane", "list", "--workspace", ws_id).get("panes", [])
                          if p["pane_id"] == pane_id)
            _h("tab", "rename", tab_id, label)
            tag_pane(pane_id, role=role, **extra)
            start(pane_id, role, name, label, claude_args=["--resume", session])
            first = False
        else:
            open_tab(ws_id, label, role, claude_args=["--resume", session], **extra)
        back.append(label)
    return {"unit": name, "workspace": ws_id, "back": back, "missing": missing}


def restore_all(only: list[str] | None = None, forget: list[str] | None = None) -> list[dict]:
    snap = _snap()
    with dispatch.locked_state() as st:
        for name in forget or []:
            st.get("image", {}).pop(name, None)
        pending = dispatch.pending_restore(snap, st)
    out = []
    for name, record in sorted(pending.items()):
        if only and name not in only:
            continue
        out.append(restore_unit(name, record))
    if out:
        with dispatch.locked_state() as st:
            seat = dispatch.panes_with_role(_snap(), "seat")
            line = "[prometheus] restored after a Herdr restart: " + "; ".join(
                "%s (back: %s%s)" % (r["unit"], ", ".join(r["back"]) or "none",
                                     "; no session: " + ", ".join(r["missing"]) if r["missing"] else "")
                for r in out)
            if seat:
                dispatch.enqueue(st, seat[0]["pane_id"], line)
            else:
                st.setdefault("seat_backlog", []).append(line)
            for r in out:
                for line in st.get("restore_backlog", {}).pop(r["unit"], []):
                    lead = dispatch.panes_with_role(_snap(), "pm", r["workspace"])
                    if lead:
                        dispatch.enqueue(st, lead[0]["pane_id"], line, unit=r["unit"])
    return out


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
    sub.add_parser("control-tabs").add_argument("workspace")
    q = sub.add_parser("quick")
    q.add_argument("workspace")
    q.add_argument("slug")
    q.add_argument("ask", nargs="+")
    rs = sub.add_parser("restore")
    rs.add_argument("--unit", action="append", default=[])
    rs.add_argument("--forget", action="append", default=[], help="drop a unit's image instead; repeatable")
    rs.add_argument("--list", action="store_true")
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
        elif a.cmd == "quick":
            print(json.dumps(quick(a.workspace, a.slug, " ".join(a.ask))))
        elif a.cmd == "control-tabs":
            print("opened: %s" % (", ".join(control_tabs(a.workspace)) or "nothing (both present)"))
        elif a.cmd == "restore":
            if a.list:
                with dispatch.locked_state() as st:
                    pending = dispatch.pending_restore(_snap(), st)
                for name, rec in sorted(pending.items()):
                    print("%s\t%s" % (name, ", ".join(x["label"] for x in rec.get("agents", []))))
                return 0
            for r in restore_all(a.unit or None, a.forget):
                print(json.dumps(r))
    except (ValueError, RuntimeError) as exc:
        print("units: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
