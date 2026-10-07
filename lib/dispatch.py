#!/usr/bin/env python3
# ---
# name: dispatch
# description: The dispatcher's engine — the only watcher. Shared state under a file lock, Herdr access, routing by workspace/pane tokens, agent-to-agent messages (send), safe-state coalesced delivery, agent-state polling, heartbeats, and the singleton loop. Shell scripts in skills/dispatch/scripts are thin wrappers over its subcommands.
# usage: dispatch.py {run|tick|stop|status|send|poll-agents|route|deliver|heartbeat} [args]
# ---
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import signal
import subprocess
import sys
import time

SAFE_STATES = ("idle", "done", "working")
LEADS = ("pm", "planner")
DEPTH3 = ("implementor", "reviewer")
INLINE_LIMIT = 400


# ------------------------------------------------------------------------ state

def state_dir() -> str:
    d = os.environ.get("PROMETHEUS_STATE_DIR") or os.path.expanduser("~/.claude/prometheus")
    os.makedirs(d, exist_ok=True)
    return d


def _empty() -> dict:
    return {"cursors": {}, "agents": {}, "ignored": [], "proposals": [], "outbox": {},
            "last_change": {}, "beats": {}}


@contextlib.contextmanager
def locked_state():
    """dispatch.json under an exclusive flock; saved atomically on clean exit."""
    d = state_dir()
    with open(os.path.join(d, "dispatch.lock"), "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = os.path.join(d, "dispatch.json")
        try:
            with open(path) as fh:
                st = {**_empty(), **json.load(fh)}
        except (OSError, ValueError):
            st = _empty()
        yield st
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(st, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)


# ------------------------------------------------------------------------ herdr

def herdr(*args: str) -> dict:
    out = subprocess.run([os.environ.get("HERDR_BIN", "herdr"), *args],
                         capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise RuntimeError("herdr %s: %s" % (" ".join(args[:3]), out.stderr.strip()))
    try:
        return json.loads(out.stdout).get("result", {})
    except ValueError:
        return {}


def snapshot() -> dict:
    return herdr("api", "snapshot").get("snapshot", {})


def _tokens(item: dict) -> dict:
    return item.get("tokens") or {}


def _csv(val: str | None) -> list[str]:
    return [v.strip() for v in (val or "").split(",") if v.strip()]


def units(snap: dict) -> list[dict]:
    """Live unit workspaces: those carrying a prometheus `unit` token."""
    return [w for w in snap.get("workspaces", []) if _tokens(w).get("unit")]


def unit_of_workspace(snap: dict, workspace_id: str) -> dict | None:
    return next((w for w in units(snap) if w["workspace_id"] == workspace_id), None)


def panes_with_role(snap: dict, role: str, workspace_id: str | None = None) -> list[dict]:
    return [p for p in snap.get("panes", [])
            if _tokens(p).get("role") == role
            and (workspace_id is None or p.get("workspace_id") == workspace_id)]


def pane(snap: dict, pane_id: str) -> dict | None:
    return next((p for p in snap.get("panes", []) if p.get("pane_id") == pane_id), None)


def lead_role(unit: dict) -> str:
    return "planner" if _tokens(unit).get("kind") == "planning" else "pm"


# ---------------------------------------------------------------------- routing

class RouteError(Exception):
    pass


def match_units(snap: dict, event: dict) -> list[dict]:
    """Units an event belongs to: by unit label, story id, or any PR in its stack."""
    if event.get("unit"):
        return [u for u in units(snap) if _tokens(u).get("unit") == event["unit"]]
    stories = set(filter(None, [event.get("story"), *event.get("stories", [])]))
    prs = set(filter(None, [event.get("pr"), *event.get("stack", [])]))
    hits = []
    for u in units(snap):
        t = _tokens(u)
        if stories & set(_csv(t.get("stories"))) or prs & set(_csv(t.get("prs"))):
            hits.append(u)
    return hits


def route(snap: dict, event: dict) -> str:
    """Event → target pane id. Raises RouteError on no match or a conflict."""
    if event.get("to_pane"):
        return event["to_pane"]
    role = event.get("role", "pm")
    if role == "seat":
        seats = panes_with_role(snap, "seat")
        if not seats:
            raise RouteError("no seat pane")
        return seats[0]["pane_id"]
    hits = match_units(snap, event)
    if len(hits) > 1:
        raise RouteError("CONFLICT: " + ",".join(_tokens(u)["unit"] for u in hits))
    if not hits:
        raise RouteError("no unit")
    unit = hits[0]
    if role in LEADS:
        role = lead_role(unit)
    targets = panes_with_role(snap, role, unit["workspace_id"])
    if event.get("item"):
        targets = [p for p in targets if _tokens(p).get("item") == event["item"]] or targets
    if not targets:
        raise RouteError("no %s pane in %s" % (role, _tokens(unit)["unit"]))
    return targets[0]["pane_id"]


def enqueue(st: dict, pane_id: str, line: str, details: dict | None = None,
            unit: str | None = None) -> None:
    st["outbox"].setdefault(pane_id, []).append(
        {"line": line, "details": details or {}, "ts": int(time.time())})
    if unit:
        st["last_change"][unit] = int(time.time())


# ------------------------------------------------------------------------- send

def send(snap: dict, st: dict, message: str, *, pane_id: str | None = None,
         role: str | None = None, unit: str | None = None) -> str:
    """Agent-to-agent: tag with sender role@unit, resolve the target, queue it."""
    me_role = os.environ.get("PROMETHEUS_ROLE", "operator")
    me_ws = os.environ.get("HERDR_WORKSPACE_ID", "")
    my_unit = unit_of_workspace(snap, me_ws)
    my_label = _tokens(my_unit).get("unit") if my_unit else "control"
    event = {"to_pane": pane_id, "role": role or "pm", "unit": unit or (my_label if my_unit else None)}
    target = route(snap, event)
    enqueue(st, target, "[prometheus] from %s@%s: %s" % (me_role, my_label, message),
            unit=event.get("unit"))
    return target


# --------------------------------------------------------------------- delivery

def _compose(pane_id: str, items: list[dict]) -> str:
    lines = [i["line"] for i in items]
    if len(items) == 1 and not items[0]["details"] and len(lines[0]) <= INLINE_LIMIT:
        return lines[0]
    d = os.path.join(state_dir(), "events", pane_id.replace(":", "_"))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%d.json" % int(time.time() * 1000))
    with open(path, "w") as fh:
        json.dump(items, fh, indent=1)
    joined = " · ".join(l.replace("[prometheus] ", "", 1) for l in lines)
    if len(joined) > INLINE_LIMIT:
        joined = joined[:INLINE_LIMIT].rsplit(" ", 1)[0] + " …"
    return "[prometheus] %d messages: %s — details: %s" % (len(items), joined, path)


def deliver(snap: dict, st: dict, prompt=None) -> dict:
    """Deliver each pane's outbox only in a safe state; coalesce to one prompt per pane."""
    prompt = prompt or (lambda p, text: herdr("agent", "prompt", p, text))
    report = {"delivered": [], "held": [], "dropped": []}
    for pane_id, items in list(st["outbox"].items()):
        if not items:
            st["outbox"].pop(pane_id)
            continue
        p = pane(snap, pane_id)
        if p is None:
            report["dropped"].append(pane_id)
            st["outbox"].pop(pane_id)
            continue
        if p.get("agent_status") not in SAFE_STATES:
            report["held"].append(pane_id)
            continue
        prompt(pane_id, _compose(pane_id, items))
        st["outbox"].pop(pane_id)
        report["delivered"].append(pane_id)
    return report


# ------------------------------------------------------------------ agent state

def poll_agents(snap: dict, st: dict) -> list[dict]:
    """Diff role-tagged panes' agent_status vs last tick; emit events for the ones that matter."""
    events, seen = [], {}
    for p in snap.get("panes", []):
        role = _tokens(p).get("role")
        if not role or role == "seat":
            continue
        pid, new = p["pane_id"], p.get("agent_status", "unknown")
        seen[pid] = new
        old = st["agents"].get(pid)
        if old is None or old == new:
            continue
        unit = unit_of_workspace(snap, p.get("workspace_id", ""))
        label = _tokens(unit).get("unit") if unit else None
        tab = _tokens(p).get("item") or role
        ev = {"kind": "agent", "pane": pid, "role": role, "unit": label, "old": old, "new": new,
              "line": "[prometheus] agent %s %s → %s" % (tab, old, new)}
        if role in DEPTH3 and (new in ("idle", "done", "blocked") or old == "blocked"):
            events.append({**ev, "route_role": "pm"})
        elif role in LEADS and new == "blocked":
            events.append({**ev, "route_role": "seat",
                           "line": "[prometheus] %s of %s is blocked" % (role, label)})
    st["agents"] = seen
    return events


def heartbeat(snap: dict, st: dict, minutes: int, now: float | None = None) -> list[dict]:
    """Units with depth-3 work in flight and no change for N minutes get one nudge per quiet spell."""
    now = now or time.time()
    events = []
    for u in units(snap):
        label = _tokens(u)["unit"]
        workers = [p for p in snap.get("panes", [])
                   if p.get("workspace_id") == u["workspace_id"] and _tokens(p).get("role") in DEPTH3]
        if not workers:
            continue
        last = st["last_change"].setdefault(label, int(now))
        if now - last < minutes * 60 or st["beats"].get(label, 0) > last:
            continue
        st["beats"][label] = int(now)
        events.append({"kind": "heartbeat", "unit": label, "route_role": "pm",
                       "line": "[prometheus] heartbeat: no movement in %s for %d min" % (label, minutes)})
    return events


# ------------------------------------------------------------------------- tick

def tick(heartbeat_min: int = 30, prompt=None) -> dict:
    snap = snapshot()
    with locked_state() as st:
        events = poll_agents(snap, st) + heartbeat(snap, st, heartbeat_min)
        unrouted = []
        for ev in events:
            try:
                target = route(snap, {"unit": ev.get("unit"), "role": ev.get("route_role", "pm")})
            except RouteError as exc:
                unrouted.append("%s (%s)" % (ev["line"], exc))
                continue
            enqueue(st, target, ev["line"], unit=ev.get("unit"))
        report = deliver(snap, st, prompt)
        report.update(events=len(events), unrouted=unrouted)
        return report


# ------------------------------------------------------------------------- loop

def _pidfile() -> str:
    return os.path.join(state_dir(), "dispatcher.pid")


def _set_token(value: str | None) -> None:
    ws = os.environ.get("HERDR_WORKSPACE_ID")
    if not ws:
        return
    args = ["workspace", "report-metadata", ws, "--source", "prometheus"]
    args += ["--token", "dispatcher=%s" % value] if value else ["--clear-token", "dispatcher"]
    with contextlib.suppress(Exception):
        herdr(*args)


def run(interval: int, heartbeat_min: int) -> int:
    lock = open(os.path.join(state_dir(), "dispatcher.run.lock"), "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("dispatcher: already running", file=sys.stderr)
        return 3
    with open(_pidfile(), "w") as fh:
        fh.write(str(os.getpid()))
    stopping = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stopping.update(now=True))
    signal.signal(signal.SIGINT, lambda *_: stopping.update(now=True))
    _set_token("running")
    print("dispatcher: running, interval %ss, heartbeat %s min" % (interval, heartbeat_min), flush=True)
    try:
        while not stopping["now"]:
            try:
                r = tick(heartbeat_min)
                if r["events"] or r["delivered"] or r["unrouted"]:
                    print(time.strftime("%H:%M:%S"), json.dumps(r), flush=True)
            except Exception as exc:  # one bad tick must not end the loop
                print(time.strftime("%H:%M:%S"), "tick failed:", exc, flush=True)
            for _ in range(interval):
                if stopping["now"]:
                    break
                time.sleep(1)
    finally:
        _set_token(None)
        with contextlib.suppress(OSError):
            os.remove(_pidfile())
    print("dispatcher: stopped", flush=True)
    return 0


def running_pid() -> int | None:
    try:
        with open(_pidfile()) as fh:
            pid = int(fh.read().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def stop() -> int:
    pid = running_pid()
    if not pid:
        print("dispatcher: not running")
        return 1
    os.kill(pid, signal.SIGTERM)
    print("dispatcher: stop sent to %d" % pid)
    return 0


# -------------------------------------------------------------------------- CLI

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="dispatch.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--interval", type=int, default=int(os.environ.get("INTERVAL", 60)))
    r.add_argument("--heartbeat", type=int, default=int(os.environ.get("HEARTBEAT", 30)))
    t = sub.add_parser("tick")
    t.add_argument("--heartbeat", type=int, default=int(os.environ.get("HEARTBEAT", 30)))
    sub.add_parser("stop")
    sub.add_parser("status")
    s = sub.add_parser("send")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--pane")
    g.add_argument("--role", choices=["pm", "planner", "implementor", "reviewer", "seat"])
    s.add_argument("--unit")
    s.add_argument("message", nargs="+")
    sub.add_parser("poll-agents")
    rt = sub.add_parser("route")
    rt.add_argument("event")
    sub.add_parser("deliver")
    hb = sub.add_parser("heartbeat")
    hb.add_argument("--minutes", type=int, default=int(os.environ.get("HEARTBEAT", 30)))
    a = ap.parse_args(argv)

    if a.cmd == "run":
        return run(a.interval, a.heartbeat)
    if a.cmd == "tick":
        print(json.dumps(tick(a.heartbeat)))
        return 0
    if a.cmd == "stop":
        return stop()
    if a.cmd == "status":
        pid = running_pid()
        print("running %d" % pid if pid else "stopped")
        return 0 if pid else 1
    snap = snapshot()
    if a.cmd == "route":
        try:
            print(route(snap, json.loads(a.event)))
            return 0
        except RouteError as exc:
            print(exc, file=sys.stderr)
            return 1
    with locked_state() as st:
        if a.cmd == "send":
            try:
                target = send(snap, st, " ".join(a.message), pane_id=a.pane, role=a.role, unit=a.unit)
            except RouteError as exc:
                print("send: %s" % exc, file=sys.stderr)
                return 1
            print("queued for %s" % target)
        elif a.cmd == "poll-agents":
            for ev in poll_agents(snap, st):
                print(json.dumps(ev))
        elif a.cmd == "deliver":
            print(json.dumps(deliver(snap, st)))
        elif a.cmd == "heartbeat":
            for ev in heartbeat(snap, st, a.minutes):
                print(json.dumps(ev))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
