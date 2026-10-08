#!/usr/bin/env python3
# ---
# name: fold
# description: Fold the running units of older kinds (story · story-set · goal-set · review) into epic units, one epic at a time with the operator watching. `plan` groups the live units by their stories' epics (cached, else one batched Shortcut lookup) and lists units with no epic. `run --epic <id>` asks each old unit's PM to write a handoff into the epic file, waits for every handoff, opens (or reuses) the epic unit with the union of stories and PRs briefed from that file, then closes each old unit whose agents are all idle — a busy one is left open and named.
# usage: fold.py plan [--json] | fold.py run --epic <id> [--wait <s>]
# ---
from __future__ import annotations

import argparse
import json
import os
import sys
import time

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import dispatch  # noqa: E402
import events  # noqa: E402
import units  # noqa: E402

LEGACY = ("story", "story-set", "goal-set", "review")


def legacy_units(snap: dict) -> list[dict]:
    return [u for u in dispatch.units(snap) if dispatch._tokens(u).get("kind") in LEGACY]


def epic_file(name: str) -> str:
    d = os.path.join(dispatch.state_dir(), "epics")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "%s.md" % name)


def plan(snap: dict, lookup=None) -> dict:
    """{epics: {id: {name, unit, units: [...], stories, prs}}, unhomed: [unit names]}"""
    olds = legacy_units(snap)
    stories = [s for u in olds for s in dispatch.token_list(dispatch._tokens(u), "stories")]
    with dispatch.locked_state() as st:
        (lookup or events.lookup_epics)(st, stories)
        cache = dict(st.get("story_epic", {}))
    out, unhomed = {}, []
    for u in olds:
        t = dispatch._tokens(u)
        ids = dispatch.token_list(t, "stories")
        epic = next(((cache[s]["id"], cache[s]["name"]) for s in ids if cache.get(s, {}).get("id")), None)
        if not epic:
            unhomed.append(t["unit"])
            continue
        e = out.setdefault(epic[0], {"name": epic[1], "unit": events.epic_unit_name(*epic), "units": [],
                                     "workspaces": [], "stories": [], "prs": [], "project": t.get("project")})
        e["units"].append(t["unit"])
        e["workspaces"].append(u["workspace_id"])
        e["stories"] += [s for s in ids if s not in e["stories"]]
        e["prs"] += [p for p in dispatch._csv(t.get("prs")) if p not in e["prs"]]
    return {"epics": out, "unhomed": unhomed}


def handoff_line(old: str, path: str) -> str:
    return ("[prometheus] from fold@control: your unit %s is folding into its epic's unit (one PM per epic). At "
            "your prompt, write your handoff into %s as a section headed exactly `## from %s`: per story its stage, "
            "PRs and heads, open threads, what it waits on, findings / proposal files, decisions already sent to the "
            "librarian. Then end your turn; this tab closes once every agent in the unit is idle." % (old, path, old))


def run(epic_id: str, wait: float = 900, lookup=None, sleep=time.sleep) -> dict:
    snap = dispatch.snapshot()
    p = plan(snap, lookup)["epics"].get(epic_id)
    if not p:
        raise ValueError("no running unit of an older kind belongs to epic %s" % epic_id)
    path = epic_file(p["unit"])
    if not os.path.exists(path):
        with open(path, "w") as fh:
            fh.write("# Epic %s — %s\n\nThe epic PM's working record. Folded from: %s.\n\n"
                     % (epic_id, p["name"], ", ".join(p["units"])))
    with dispatch.locked_state() as st:
        for old, ws in zip(p["units"], p["workspaces"]):
            lead = dispatch.panes_with_role(snap, "pm", ws)
            if lead:
                dispatch.enqueue(st, lead[0]["pane_id"], handoff_line(old, path), unit=old)
    dispatch.poke()
    deadline, missing = time.time() + wait, list(p["units"])
    while missing and time.time() < deadline:
        text = open(path).read()
        missing = [u for u in p["units"] if "## from %s" % u not in text]
        if missing:
            sleep(5)
    if missing:
        return {"epic": epic_id, "folded": [], "waiting": missing,
                "note": "handoffs not written in %ds — nothing opened or closed; run again" % wait}
    snap = dispatch.snapshot()
    existing = next((u for u in dispatch.units(snap) if dispatch._tokens(u).get("epic") == epic_id), None)
    if existing:
        units.set_tokens(existing["workspace_id"], add_stories=p["stories"], add_prs=p["prs"])
        with dispatch.locked_state() as st:
            lead = dispatch.panes_with_role(snap, "pm", existing["workspace_id"])
            if lead:
                dispatch.enqueue(st, lead[0]["pane_id"], "[prometheus] from fold@control: folded %s into your epic — "
                                 "read their sections in %s and take over each story and PR from there."
                                 % (", ".join(p["units"]), path), unit=dispatch._tokens(existing)["unit"])
        target = existing["workspace_id"]
    else:
        with dispatch.locked_state() as st:
            target = events.create_unit(
                st, p["unit"], "epic", p["project"] or events.default_project() or "besstie", p["stories"], p["prs"],
                "Epic %s (%s), opened by folding %s. Every story and PR below is yours: read each `## from <unit>` "
                "section of your epic file first and resume every story and PR exactly where it stands — nothing is "
                "restarted." % (p["name"], epic_id, ", ".join(p["units"])), epic=epic_id)
    closed, left = [], []
    for old, ws in zip(p["units"], p["workspaces"]):
        try:
            units.close(ws)
            closed.append(old)
        except ValueError as exc:
            left.append("%s (%s)" % (old, exc))
    with dispatch.locked_state() as st:
        events._to_seat(dispatch.snapshot(), st, "[prometheus] fold: epic %s → %s; closed %s%s"
                        % (epic_id, p["unit"], ", ".join(closed) or "none",
                           "; still open (busy): " + "; ".join(left) if left else ""))
    return {"epic": epic_id, "unit": p["unit"], "workspace": target, "folded": closed, "left_open": left}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="fold.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan")
    pl.add_argument("--json", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--epic", required=True)
    r.add_argument("--wait", type=float, default=900)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":
            out = plan(dispatch.snapshot())
            if a.json:
                print(json.dumps(out, indent=1))
            else:
                for eid, e in sorted(out["epics"].items()):
                    print("epic %s %s → %s\n  units: %s\n  stories: %s\n  prs: %s"
                          % (eid, e["name"], e["unit"], ", ".join(e["units"]), ", ".join(e["stories"]),
                             ", ".join(e["prs"]) or "—"))
                if out["unhomed"]:
                    print("no epic: %s" % ", ".join(out["unhomed"]))
        else:
            print(json.dumps(run(a.epic, a.wait), indent=1))
    except (ValueError, RuntimeError) as exc:
        print("fold: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
