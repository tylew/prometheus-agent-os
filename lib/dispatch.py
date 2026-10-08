#!/usr/bin/env python3
# ---
# name: dispatch
# description: The dispatcher's engine — the only watcher. Shared state under a file lock, routing by workspace/pane tokens, agent-to-agent messages (send), agents' self-reports (status / needs-you tokens), safe-state coalesced delivery, agent-state polling, heartbeats, the restore image, and the singleton loop woken by Herdr events. Shell scripts in skills/dispatch/scripts are thin wrappers over its subcommands.
# usage: dispatch.py {run|tick|stop|status|send|report|poll-agents|route|deliver|heartbeat} [args]
# ---
from __future__ import annotations

import argparse
import contextlib
import copy
import fcntl
import json
import os
import re
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env  # noqa: E402
import herdr as hz  # noqa: E402

SAFE_STATES = ("idle", "done", "working")
LEADS = ("pm",)
DEPTH3 = ("implementor", "reviewer")
CHILDREN = DEPTH3 + ("planner",)
CONTROL = ("seat", "librarian")
ROLES = ("seat", "librarian", "runner", "configurator", "pm", "planner", "implementor", "reviewer")
INLINE_LIMIT = 400


# ------------------------------------------------------------------------ state

def state_dir() -> str:
    d = env.state_dir()
    os.makedirs(d, exist_ok=True)
    return d


def _empty() -> dict:
    return {"cursors": {}, "agents": {}, "ignored": [], "proposals": [], "outbox": {},
            "last_change": {}, "beats": {}, "image": {}}


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
    return hz.call(*args)


def submit(pane_id: str, text: str) -> str:
    """Submit a prompt and confirm a turn started (Herdr's prompt --wait; resent only on a stall)."""
    return hz.prompt_wait(pane_id, text)


DIALOG_MARKERS = ("Enter to select", "Esc to cancel", "to navigate", "Do you want to proceed", "Type something")


def input_busy(pane_id: str) -> str | None:
    """Why typing into this pane now would collide, or None. Herdr reports an open choice dialog as
    done/idle, and text already on the prompt line (the operator typing) would be glued to ours."""
    lines = [l.rstrip() for l in hz.read(pane_id).splitlines() if l.strip()][-12:]
    if any(m in l for l in lines for m in DIALOG_MARKERS):
        return "dialog open"
    prompts = [l for l in lines if l.lstrip().startswith("❯")]
    if prompts and prompts[-1].lstrip()[1:].strip():
        return "input line not empty"
    return None


def snapshot() -> dict:
    return hz.snapshot()


def _tokens(item: dict) -> dict:
    return item.get("tokens") or {}


def _csv(val: str | None) -> list[str]:
    return [v.strip() for v in (val or "").split(",") if v.strip()]


PR_REF_RE = re.compile(r"^[\w.-]+/[\w.-]+#\d+$")


def canon_ref(key: str, value: str) -> str:
    """A `stories` / `prs` token entry in its one form: sc-N (bare N accepted) · owner/repo#n (else ValueError)."""
    if key == "stories":
        return "sc-" + value if value.isdigit() else value
    if not PR_REF_RE.match(value):
        raise ValueError("PR ref must be owner/repo#n: %r" % value)
    return value


def token_list(tokens: dict, key: str) -> list[str]:
    """A unit's stories / prs as written; story ids canonical, so a bare id still matches."""
    vals = _csv(tokens.get(key))
    return [canon_ref(key, v) for v in vals] if key == "stories" else vals


def owned(name: str) -> bool:
    """`prom-test-*` units belong only to e2e (PROMETHEUS_TEST_UNITS=1), never the operator's dispatcher."""
    return not name.startswith("prom-test-") or os.environ.get("PROMETHEUS_TEST_UNITS") == "1"


def units(snap: dict) -> list[dict]:
    """Live unit workspaces this dispatcher owns: those carrying a prometheus `unit` token."""
    return [w for w in snap.get("workspaces", []) if _tokens(w).get("unit") and owned(_tokens(w)["unit"])]


def unit_of_workspace(snap: dict, workspace_id: str) -> dict | None:
    return next((w for w in units(snap) if w["workspace_id"] == workspace_id), None)


def unit_of_pane(snap: dict, pane_id: str) -> dict | None:
    p = pane(snap, pane_id)
    return unit_of_workspace(snap, p.get("workspace_id", "")) if p else None


def panes_with_role(snap: dict, role: str, workspace_id: str | None = None) -> list[dict]:
    return [p for p in snap.get("panes", [])
            if _tokens(p).get("role") == role
            and (workspace_id is None or p.get("workspace_id") == workspace_id)]


def pane(snap: dict, pane_id: str) -> dict | None:
    return next((p for p in snap.get("panes", []) if p.get("pane_id") == pane_id), None)


def control_workspace(snap: dict) -> str | None:
    live = [w["workspace_id"] for w in snap.get("workspaces", []) if _tokens(w).get("dispatcher") == "running"]
    return live[0] if len(live) == 1 else os.environ.get("HERDR_WORKSPACE_ID") if len(live) > 1 else None


def lead_role(unit: dict) -> str:
    return "pm"


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
        if stories & set(token_list(t, "stories")) or prs & set(_csv(t.get("prs"))):
            hits.append(u)
    return hits


def route(snap: dict, event: dict) -> str:
    """Event → target pane id. Raises RouteError on no match or a conflict."""
    if event.get("to_pane"):
        return event["to_pane"]
    role = event.get("role", "pm")
    if role in CONTROL:
        # several control workspaces may exist (a trial beside the real one): the running dispatcher's wins
        control = control_workspace(snap)
        found = panes_with_role(snap, role, control) if control else []
        found = found or panes_with_role(snap, role)
        if not found:
            raise RouteError("no %s pane" % role)
        return found[0]["pane_id"]
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
    my_unit = unit_of_pane(snap, os.environ.get("HERDR_PANE_ID", "")) or \
        unit_of_workspace(snap, os.environ.get("HERDR_WORKSPACE_ID", ""))
    my_label = _tokens(my_unit).get("unit") if my_unit else "control"
    event = {"to_pane": pane_id, "role": role or "pm", "unit": unit or (my_label if my_unit else None)}
    if event["role"] in CONTROL:
        event["unit"] = None
    target = route(snap, event)
    enqueue(st, target, "[prometheus] from %s@%s: %s" % (me_role, my_label, message),
            unit=event.get("unit"))
    return target


def report(snap: dict, st: dict, text: str, needs: bool = False, clear: bool = False) -> str:
    """An agent's own map line (`status` token); --needs-you also flags it and asks the seat."""
    me = os.environ.get("HERDR_PANE_ID")
    if not me:
        raise RouteError("report needs HERDR_PANE_ID (run inside an agent pane)")
    if clear:
        herdr("pane", "report-metadata", me, "--source", "prometheus", "--clear-token", "status",
              "--clear-token", "needs")
        return "cleared"
    args = ["pane", "report-metadata", me, "--source", "prometheus", "--token", "status=%s" % text[:120]]
    if needs:
        args += ["--token", "needs=1"]
    herdr(*args)
    if not needs:
        return "status set"
    p = pane(snap, me) or {}
    role = _tokens(p).get("role") or os.environ.get("PROMETHEUS_ROLE", "agent")
    unit = unit_of_pane(snap, me)
    where = "%s@%s" % (role, _tokens(unit).get("unit") if unit else "control")
    line = "[prometheus] needs you — %s (%s): %s — answer with send.sh --pane %s" % (where, me, text, me)
    try:
        enqueue(st, route(snap, {"role": "seat"}), line)
    except RouteError:
        st.setdefault("seat_backlog", []).append(line)
    return "needs-you sent to the seat"


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
    report, sends = take_deliveries(snap, st, real=prompt is None)
    send_all(sends, prompt)
    return report


def take_deliveries(snap: dict, st: dict, real: bool = True) -> tuple[dict, list[dict]]:
    """Under the state lock: pick what can be delivered now and take it out of the outbox. Sending
    happens after the lock is released (send_all), so no agent waits on a slow prompt."""
    report, sends = {"delivered": [], "held": [], "dropped": []}, []
    for pane_id, items in list(st["outbox"].items()):
        if not items:
            st["outbox"].pop(pane_id)
            continue
        p = pane(snap, pane_id)
        if p is None:
            report["dropped"].append(pane_id)
            st["outbox"].pop(pane_id)
            continue
        if p.get("agent_status") not in SAFE_STATES or (real and input_busy(pane_id)):
            report["held"].append(pane_id)
            continue
        sends.append({"pane": pane_id, "items": items})
        st["outbox"].pop(pane_id)
        report["delivered"].append(pane_id)
    return report, sends


def send_all(sends: list[dict], prompt=None) -> list[dict]:
    """Send taken deliveries; return the ones that failed (the caller puts them back)."""
    failed = []
    for d in sends:
        try:
            # a queued slash command (/compact …) goes alone and unwrapped, after the messages
            slash = [i for i in d["items"] if i["line"].startswith("/")]
            rest = [i for i in d["items"] if not i["line"].startswith("/")]
            if rest:
                (prompt or submit)(d["pane"], _compose(d["pane"], rest))
            for item in slash:
                herdr("agent", "prompt", d["pane"], item["line"]) if prompt is None else prompt(d["pane"], item["line"])
        except Exception:  # noqa: BLE001 — a failed send is requeued, never lost
            failed.append(d)
    return failed


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
        if new == "working" and _tokens(p).get("needs"):
            with contextlib.suppress(Exception):
                herdr("pane", "report-metadata", pid, "--source", "prometheus", "--clear-token", "needs")
        if old is None or old == new:
            continue
        if role in ("runner", "configurator"):
            if new == "blocked":  # a permission prompt in a seat-opened tab: the operator approves it there
                tab = ("quick-" if role == "runner" else "config-") + (_tokens(p).get("item") or role)
                events.append({"kind": "agent", "pane": pid, "role": role, "unit": None, "route_role": "seat",
                               "line": "[prometheus] needs you — %s (%s) is waiting on a permission prompt "
                                       "in its tab" % (tab, pid)})
            continue
        if role == "librarian":
            if new == "blocked":
                events.append({"kind": "agent", "pane": pid, "role": role, "unit": None, "route_role": "seat",
                               "line": "[prometheus] the librarian is blocked"})
            continue
        unit = unit_of_pane(snap, pid)
        label = _tokens(unit).get("unit") if unit else None
        tab = _tokens(p).get("item") or role
        ev = {"kind": "agent", "pane": pid, "role": role, "unit": label, "old": old, "new": new,
              "line": "[prometheus] agent %s %s → %s" % (tab, old, new)}
        if role in CHILDREN and (new in ("idle", "done", "blocked") or old == "blocked"):
            events.append({**ev, "route_role": "pm"})
        elif role in LEADS and new == "blocked":
            events.append({**ev, "route_role": "seat",
                           "line": "[prometheus] %s of %s is blocked" % (role, label)})
    st["agents"] = seen
    return events


def dialogs(snap: dict, st: dict, probe=None) -> list[dict]:
    """Herdr shows an agent waiting in a question dialog as idle / done. Flag each newly opened one on the
    map (needs token) and tell the seat once; forget it when the dialog closes."""
    probe = probe or input_busy
    open_now, events = {}, []
    for p in snap.get("panes", []):
        role = _tokens(p).get("role")
        if not role or role == "seat" or p.get("agent_status") not in ("idle", "done"):
            continue
        if probe(p["pane_id"]) != "dialog open":
            continue
        pid = p["pane_id"]
        open_now[pid] = True
        if pid in st.get("dialogs", {}):
            continue
        unit = unit_of_pane(snap, pid)
        where = "%s@%s" % (role, _tokens(unit).get("unit") if unit else "control")
        with contextlib.suppress(Exception):
            herdr("pane", "report-metadata", pid, "--source", "prometheus", "--token", "needs=1")
        events.append({"kind": "dialog", "pane": pid, "unit": None, "route_role": "seat",
                       "line": "[prometheus] needs you — %s (%s) has a question open in its tab; answer it there"
                       % (where, pid)})
    st["dialogs"] = open_now
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


# ---------------------------------------------------------------- restore image

def session_of(p: dict) -> str | None:
    sess = p.get("agent_session")
    return (sess.get("value") if isinstance(sess, dict) else sess) or None


def update_image(snap: dict, st: dict) -> None:
    """Record every live unit: its tokens and, per agent tab, label + pane tokens + Claude session.
    Units not live keep their last image — that is what a Herdr restart leaves to restore."""
    tabs = {t["tab_id"]: t.get("label") for t in snap.get("tabs", [])}
    image = st.setdefault("image", {})
    for k in [k for k in image if not owned(k)]:
        del image[k]
    for u in units(snap):
        label = _tokens(u)["unit"]
        agents = []
        for p in snap.get("panes", []):
            if p.get("workspace_id") != u["workspace_id"] or not _tokens(p).get("role"):
                continue
            prev = next((a for a in image.get(label, {}).get("agents", [])
                         if a["label"] == tabs.get(p.get("tab_id"))), {})
            agents.append({"label": tabs.get(p.get("tab_id")) or _tokens(p)["role"],
                           "tokens": {k: v for k, v in _tokens(p).items() if k not in ("status", "needs")},
                           "session": session_of(p) or prev.get("session")})
        agents.sort(key=lambda a: a["tokens"].get("role") != lead_role(u))
        image[label] = {"tokens": dict(_tokens(u)), "agents": agents, "ts": int(time.time())}


def pending_restore(snap: dict, st: dict) -> dict:
    live = {_tokens(u)["unit"] for u in units(snap)}
    return {k: v for k, v in st.get("image", {}).items() if k not in live and owned(k)}


# ------------------------------------------------------------------------- tick

def tick(heartbeat_min: int = 30, prompt=None, external: bool | None = None) -> dict:
    """external=True runs the GitHub / Shortcut sources and unit health too; an event-woken tick only
    polls agents and delivers."""
    snap = snapshot()
    if external is None:
        external = os.environ.get("PROMETHEUS_EXTERNAL", "1") == "1"
    log = []
    if external:
        # GitHub / Shortcut / triage / unit creation are slow and can hang: run them on a copy with the
        # lock released, then merge what they changed — send.sh and friends never wait on the network.
        import events as ext
        with locked_state() as st:
            base = copy.deepcopy(st)
        work = copy.deepcopy(base)
        try:
            log = ext.tick(snap, work)
        except Exception as exc:  # noqa: BLE001 — one failed source must not stop agents being served
            log = ["external tick failed: %s" % exc]
        with locked_state() as st:
            merge_state(base, work, st)
        snap = snapshot()
    with locked_state() as st:
        update_image(snap, st)
        seats = panes_with_role(snap, "seat")
        if seats and st.get("seat_backlog"):
            for line in st.pop("seat_backlog"):
                enqueue(st, seats[0]["pane_id"], line)
        events = poll_agents(snap, st) + heartbeat(snap, st, heartbeat_min)
        if prompt is None:
            events += dialogs(snap, st)
        unrouted = []
        for ev in events:
            try:
                target = route(snap, {"unit": ev.get("unit"), "role": ev.get("route_role", "pm")})
            except RouteError as exc:
                unrouted.append("%s (%s)" % (ev["line"], exc))
                continue
            enqueue(st, target, ev["line"], unit=ev.get("unit"))
        report, sends = take_deliveries(snap, st, real=prompt is None)
    failed = send_all(sends, prompt)
    if failed:
        with locked_state() as st:
            for d in failed:
                st["outbox"][d["pane"]] = d["items"] + st["outbox"].get(d["pane"], [])
                report["delivered"].remove(d["pane"])
                report["held"].append(d["pane"])
    report.update(events=len(events), unrouted=unrouted, log=log)
    return report


def merge_state(base: dict, work: dict, st: dict) -> None:
    """Fold changes made on `work` (a copy of `base`) into the live `st`, keeping what others wrote
    meanwhile: list additions / removals and changed dict entries apply; outbox items append."""
    for key, new in work.items():
        old = base.get(key)
        if new == old:
            continue
        cur = st.get(key)
        if key == "outbox":
            for pane_id, items in new.items():
                added = items[len((old or {}).get(pane_id, [])):]
                if added:
                    st["outbox"].setdefault(pane_id, []).extend(added)
        elif isinstance(new, dict) and isinstance(cur, dict) and isinstance(old, dict):
            for k in set(new) | set(old):
                if new.get(k) != old.get(k):
                    if k in new:
                        cur[k] = new[k]
                    else:
                        cur.pop(k, None)
        elif isinstance(new, list) and isinstance(cur, list) and isinstance(old, list):
            st[key] = [x for x in cur if x in new or x not in old] + [x for x in new if x not in old and x not in cur]
        else:
            st[key] = new


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
    watcher = hz.Watcher()
    watcher.start()
    signal.signal(signal.SIGUSR1, lambda *_: watcher.changed.set())  # poke(): a message was queued
    print("dispatcher: running, interval %ss, heartbeat %s min" % (interval, heartbeat_min), flush=True)
    external_env = os.environ.get("PROMETHEUS_EXTERNAL", "1") == "1"
    next_full = 0.0
    try:
        while not stopping["now"]:
            full = time.time() >= next_full
            try:
                r = tick(heartbeat_min, external=external_env and full)
                if r["events"] or r["delivered"] or r["unrouted"] or r["log"]:
                    print(time.strftime("%H:%M:%S"), json.dumps(r), flush=True)
                with contextlib.suppress(Exception):
                    watcher.watch(p["pane_id"] for p in snapshot().get("panes", []) if _tokens(p).get("role"))
            except Exception as exc:  # one bad tick must not end the loop
                print(time.strftime("%H:%M:%S"), "tick failed:", exc, flush=True)
            if full:
                next_full = time.time() + interval
            # sleep until a Herdr event or the next full tick; 1s steps keep SIGTERM responsive
            while not stopping["now"] and time.time() < next_full:
                if watcher.wait(min(1.0, max(0.0, next_full - time.time()))):
                    time.sleep(0.5)  # let a burst of events settle into one tick
                    watcher.changed.clear()
                    break
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


def poke() -> None:
    """Wake the loop now so a queued message is delivered without waiting for the next tick."""
    pid = running_pid()
    if pid:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGUSR1)


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
    g.add_argument("--role", choices=list(ROLES))
    s.add_argument("--unit")
    s.add_argument("message", nargs="+")
    rp = sub.add_parser("report")
    rp.add_argument("--needs-you", action="store_true")
    rp.add_argument("--clear", action="store_true")
    rp.add_argument("text", nargs="*")
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
            poke()
        elif a.cmd == "report":
            if not a.clear and not a.text:
                print("report: give a line, or --clear", file=sys.stderr)
                return 2
            try:
                print(report(snap, st, " ".join(a.text), needs=a.needs_you, clear=a.clear))
                poke()
            except RouteError as exc:
                print("report: %s" % exc, file=sys.stderr)
                return 1
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
