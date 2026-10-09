#!/usr/bin/env python3
# ---
# name: unit_engine
# description: The unit engine — per-story pipeline state for units switched on (`engine=on` workspace token), kept in the dispatcher state under `engine` (merged per field), fed by the agents' inbox (report.sh --stopped|--idr|--done) and the lead-routed event lines, with every observation and decision appended to the unit's feed (<state>/engine/<unit>.feed). Runs in the dispatcher's external, unlocked phase. Shadow mode: it records what it sees and what it would do; a duty acts only once listed in the unit's `engine_act` token.
# usage: unit_engine.py status [--unit <label>] | on <unit> | off <unit> | act <unit> <duty>[,<duty>…] | feed <unit> [-n N]
# ---
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dispatch  # noqa: E402

STAGES = ("backlog", "ready", "design", "implement", "stopped", "review", "approval", "validate", "ask",
          "merging", "done")
WAITING = ("stopped", "ask")
DUTIES = ("review", "pull", "design", "publish", "stops", "approval", "validate", "restack", "close")
REPORT_STAGE = {"idr": ("design", "IDR check"), "stopped": ("stopped", "the stop's owner"),
                "done": ("review", "round 1")}


def engine_dir() -> str:
    return os.path.join(dispatch.state_dir(), "engine")


def inbox_dir() -> str:
    return os.path.join(engine_dir(), "inbox")


def feed_path(unit: str) -> str:
    return os.path.join(engine_dir(), "%s.feed" % unit)


def feed(unit: str, text: str, now: float | None = None) -> None:
    os.makedirs(engine_dir(), exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now or time.time()))
    with open(feed_path(unit), "a") as fh:
        fh.write("%s  %s\n" % (stamp, text.replace("\n", " ")))


def tail(unit: str, n: int = 10) -> list[str]:
    try:
        with open(feed_path(unit)) as fh:
            return [l.rstrip("\n") for l in fh.readlines()[-n:]]
    except OSError:
        return []


def engine_units(snap: dict) -> list[dict]:
    return [u for u in dispatch.units(snap) if dispatch._tokens(u).get("engine") == "on"]


def acting(unit: dict, duty: str) -> bool:
    return duty in dispatch._csv(dispatch._tokens(unit).get("engine_act"))


def _stories(st: dict) -> dict:
    return st.setdefault("engine", {}).setdefault("stories", {})


def story_state(st: dict, story: str, unit: str | None = None) -> dict:
    sid = story if story.startswith("sc-") else "sc-%s" % story
    rec = _stories(st).setdefault(sid, {"story": sid, "unit": unit, "stage": "backlog", "waiting": None,
                                        "intents": {}, "legacy": False})
    if unit and not rec.get("unit"):
        rec["unit"] = unit
    return rec


def set_stage(st: dict, rec: dict, stage: str, waiting: str | None, why: str, now: float | None = None) -> bool:
    if stage not in STAGES:
        raise ValueError("unknown stage %r" % stage)
    if (rec["stage"], rec.get("waiting")) == (stage, waiting):
        return False
    old = rec["stage"]
    rec.update(stage=stage, waiting=waiting, since=int(now or time.time()))
    if rec.get("unit"):
        feed(rec["unit"], "%s: %s → %s%s — %s" % (rec["story"], old, stage,
                                                   " (waiting: %s)" % waiting if waiting else "", why), now)
    return True


def intend(rec: dict, kind: str, key: str) -> bool:
    """Record an intent before a side effect; False when the same intent already exists (the caller then
    checks the external fact instead of redoing it)."""
    k = "%s:%s" % (kind, key)
    if k in rec["intents"]:
        return False
    rec["intents"][k] = int(time.time())
    return True


# ------------------------------------------------------------------- adoption

def adopt(snap: dict, st: dict, unit: dict, now: float | None = None) -> list[str]:
    """Stories in an engine unit's `stories` token get a record; one past ready when first seen is legacy
    (started under the PM: no IDR or scenario-test gate). Stage starts from the PM-kept `stages` token."""
    t = dispatch._tokens(unit)
    label = t.get("unit")
    stages = dict(kv.split("=", 1) for kv in dispatch._csv(t.get("stages")) if "=" in kv)
    log = []
    for sid in dispatch.token_list(t, "stories"):
        sid = sid if sid.startswith("sc-") else "sc-%s" % sid
        if sid in _stories(st):
            continue
        rec = story_state(st, sid, label)
        token_stage = stages.get(sid)
        stage = token_stage if token_stage in STAGES else "backlog"
        rec["legacy"] = stage not in ("backlog", "ready")
        set_stage(st, rec, stage, None, "adopted%s" % (" (legacy)" if rec["legacy"] else ""), now)
        log.append("engine: adopted %s in %s at %s" % (sid, label, stage))
    return log


# ---------------------------------------------------------------------- inbox

def consume_inbox(snap: dict, st: dict, now: float | None = None) -> list[str]:
    """Apply each agent report to its story's state and feed; move the file to inbox/done."""
    box = inbox_dir()
    if not os.path.isdir(box):
        return []
    on = {dispatch._tokens(u).get("unit") for u in engine_units(snap)}
    done = os.path.join(box, "done")
    os.makedirs(done, exist_ok=True)
    log = []
    for name in sorted(f for f in os.listdir(box) if f.endswith(".json")):
        path = os.path.join(box, name)
        try:
            with open(path) as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            os.replace(path, os.path.join(done, name))
            continue
        unit, story = rec.get("unit"), rec.get("story")
        if unit in on and story:
            s = story_state(st, story, unit)
            stage, waiting = REPORT_STAGE[rec["kind"]]
            s.setdefault("files", {})[rec["kind"]] = rec["file"]
            set_stage(st, s, stage, waiting, "%s reported by %s (%s): %s" % (rec["kind"], rec.get("role"),
                                                                              rec.get("pane"), rec["file"]), now)
            log.append("engine: %s %s → %s" % (story, rec["kind"], stage))
        elif unit:
            feed(unit, "inbox %s from %s (%s) on %s: %s" % (rec["kind"], rec.get("role"), rec.get("pane"),
                                                             story, rec["file"]), now)
        os.replace(path, os.path.join(done, name))
    return log


def observe(snap: dict, ev: dict, now: float | None = None) -> None:
    """A lead-routed event line for an engine unit goes to its feed too (shadow: the PM still acts on it)."""
    unit = ev.get("unit")
    if unit and any(dispatch._tokens(u).get("unit") == unit for u in engine_units(snap)):
        feed(unit, "event: %s" % ev.get("line", ""), now)


# ----------------------------------------------------------------------- tick

def reconcile(snap: dict, st: dict, unit: dict, now: float | None = None) -> list[str]:
    """Shadow: where the PM-kept `stages` token disagrees with the engine's stage, record it."""
    t = dispatch._tokens(unit)
    label = t.get("unit")
    stages = dict(kv.split("=", 1) for kv in dispatch._csv(t.get("stages")) if "=" in kv)
    log = []
    for sid, pm_stage in stages.items():
        rec = _stories(st).get(sid)
        if rec and rec["unit"] == label and pm_stage != rec["stage"]:
            key = "%s:%s" % (pm_stage, rec["stage"])
            if rec.get("last_mismatch") != key:
                rec["last_mismatch"] = key
                feed(label, "shadow: %s — PM says %s, engine says %s" % (sid, pm_stage, rec["stage"]), now)
                log.append("engine: %s stage mismatch" % sid)
    return log


def tick(snap: dict, st: dict, now: float | None = None) -> list[str]:
    if dispatch.pending_restore(snap, st):
        return ["engine: waiting for restore"]
    log = []
    for u in engine_units(snap):
        log += adopt(snap, st, u, now)
    log += consume_inbox(snap, st, now)
    for u in engine_units(snap):
        log += reconcile(snap, st, u, now)
    return log


# ------------------------------------------------------------------------ CLI

def _set_unit_tokens(label: str, **tokens: str) -> None:
    snap = dispatch.snapshot()
    hit = [u for u in dispatch.units(snap) if dispatch._tokens(u).get("unit") == label]
    if not hit:
        raise SystemExit("no unit %s" % label)
    import units
    units.tag_workspace(hit[0]["workspace_id"], **tokens)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="unit_engine.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status")
    s.add_argument("--unit")
    sub.add_parser("on").add_argument("unit")
    sub.add_parser("off").add_argument("unit")
    a_ = sub.add_parser("act")
    a_.add_argument("unit")
    a_.add_argument("duties")
    f = sub.add_parser("feed")
    f.add_argument("unit")
    f.add_argument("-n", type=int, default=20)
    a = ap.parse_args(argv)
    if a.cmd == "status":
        with dispatch.locked_state() as st:
            rows = [r for r in _stories(st).values() if not a.unit or r.get("unit") == a.unit]
        for r in sorted(rows, key=lambda r: (r.get("unit") or "", r["story"])):
            print("%-10s %-24s %-10s %s%s" % (r["story"], r.get("unit") or "-", r["stage"],
                                              "waiting: %s" % r["waiting"] if r.get("waiting") else "",
                                              " (legacy)" if r.get("legacy") else ""))
        return 0
    if a.cmd in ("on", "off"):
        _set_unit_tokens(a.unit, engine=a.cmd)
        feed(a.unit, "engine %s (shadow until a duty is listed with `act`)" % a.cmd)
        print("engine %s for %s" % (a.cmd, a.unit))
        return 0
    if a.cmd == "act":
        duties = dispatch._csv(a.duties)
        bad = [d for d in duties if d not in DUTIES]
        if bad:
            raise SystemExit("unknown duty %s — one of %s" % (", ".join(bad), ", ".join(DUTIES)))
        _set_unit_tokens(a.unit, engine_act=",".join(duties))
        feed(a.unit, "engine acts on: %s" % (", ".join(duties) or "nothing (shadow)"))
        print("engine acts on %s for %s" % (", ".join(duties) or "nothing", a.unit))
        return 0
    if a.cmd == "feed":
        print("\n".join(tail(a.unit, a.n)))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
