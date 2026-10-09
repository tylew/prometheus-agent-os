#!/usr/bin/env python3
# ---
# name: rounds
# description: PR events go to the agent that holds the PR, and review rounds open themselves. A PR's CI / review / comment changes reach the implementor or working reviewer whose `pr` token names it, else the PM (a teammate's CI never does); merged / closed / ready / draft / new always reach the PM. A PR whose review round was briefed is in the loop: on a teammate's PR new commits open the next round once the head has settled; on the operator's own PR the PM opens it with `next` once its round comment is posted — a fresh `review-<pr#>` tab briefed from the last round's brief with `round` + 1 — and the PM gets one line; `hold` keeps a PR out (the PM's veto).
# usage: rounds.py hold <owner/repo#n> [--off] | rounds.py next <owner/repo#n> | rounds.py list
# ---
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import dispatch  # noqa: E402

PM_CHANGES = ("new", "merged", "closed", "ready for review", "back to draft")
HOLDERS = ("implementor", "reviewer")


def settle_secs() -> int:
    return int(os.environ.get("PROMETHEUS_ROUND_SETTLE", "300"))


def holders(snap: dict, workspace_id: str, ref: str) -> list[dict]:
    return [p for p in snap.get("panes", []) if p.get("workspace_id") == workspace_id
            and dispatch._tokens(p).get("role") in HOLDERS and ref in dispatch._csv(dispatch._tokens(p).get("pr"))]


def targets(snap: dict, st: dict, unit: dict, ev: dict, operator: str = "") -> dict:
    """{pane id: [changes]} for one PR event; "new commits" on a PR in the loop schedules a round instead."""
    ref, ws = ev["pr"], unit["workspace_id"]
    held = holders(snap, ws, ref)
    impl = next((p for p in held if dispatch._tokens(p)["role"] == "implementor"), None)
    rev = next((p for p in held if dispatch._tokens(p)["role"] == "reviewer" and p.get("agent_status") == "working"), None)
    pm = dispatch.route(snap, {"unit": dispatch._tokens(unit)["unit"], "role": "pm"})
    teammate = bool(ev.get("author")) and ev.get("author") != operator
    loop = st.setdefault("loops", {}).get(ref)
    out: dict = {}
    for change in ev.get("changes") or [ev.get("change", "")]:
        if change in PM_CHANGES:
            to = pm
            if change in ("merged", "closed"):
                st["loops"].pop(ref, None)
        elif change == "new commits":
            if rev:
                to = rev["pane_id"]
            elif loop and not loop.get("held") and teammate:
                loop.update(due=int(time.time()) + settle_secs(), head=ev.get("head"))
                continue
            elif impl:
                continue  # the implementor pushed them
            else:
                to = pm
        elif change.startswith("ci "):
            to = impl["pane_id"] if impl else rev["pane_id"] if rev else None if teammate else pm
        else:
            to = impl["pane_id"] if impl else rev["pane_id"] if rev else pm
        if to:
            out.setdefault(to, []).append(change)
    return out


def record(st: dict, ref: str, unit: str, workspace_id: str, brief: str) -> None:
    """A briefed review round puts its PR in the loop; the brief is the template for the next round."""
    st.setdefault("loops", {})[ref] = {"unit": unit, "workspace": workspace_id, "brief": os.path.abspath(brief),
                                       "round": _round(brief), "held": st.get("loops", {}).get(ref, {}).get("held", False)}


def _round(brief: str) -> int:
    try:
        with open(brief) as fh:
            m = re.search(r"^round:\s*(\d+)", fh.read(), re.M)
    except OSError:
        return 1
    return int(m.group(1)) if m else 1


def next_brief(loop: dict, ref: str, head: str | None) -> str:
    """The last round's brief with round + 1, its artifact renamed, and the due check put first."""
    with open(loop["brief"]) as fh:
        text = fh.read()
    prev = re.search(r"^artifact:\s*(.*-r)\d+\.md", text, re.M)
    n = loop["round"] + 1
    text = re.sub(r"^round:\s*\d+", "round: %d" % n, text, count=1, flags=re.M)
    text = re.sub(r"(^artifact:.*-r)\d+(\.md)", r"\g<1>%d\2" % n, text, count=1, flags=re.M)
    text += ("\n\n## Round %d — opened by the dispatcher\n\nNew commits on %s (head %s). Before anything else, "
             "run *Is a round due?* (`review` → `references/review-loop.md`) and the SKILL.md preconditions; "
             "not due (a pure restack, a label, a round already posted at this head) ⇒ post nothing and report "
             "`not due: <why>`. Prior rounds: every `%s*.md` findings file. Open threads: read them fresh.\n"
             % (n, ref, head or "?", prev.group(1) if prev else "<state>/reviews/<owner>-<repo>-<pr>-r"))
    path = os.path.join(dispatch.state_dir(), "reviews", "briefs", "%s-r%d.md" % (re.sub(r"[/#]", "-", ref), n))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    return path


def due(snap: dict, st: dict, now: float | None = None) -> list[tuple[str, dict]]:
    now = now or time.time()
    out = []
    for ref, loop in sorted(st.get("loops", {}).items()):
        if not loop.get("due") or loop["due"] > now or loop.get("held"):
            continue
        cur = st.get("cursors", {}).get("pr:" + ref) or {}
        if cur.get("state") not in (None, "open") or cur.get("draft"):
            loop.pop("due", None)
            continue
        if cur.get("head") and loop.get("head") and cur["head"] != loop["head"]:
            continue  # moved again since it was scheduled: the next poll reschedules it
        if any(p.get("agent_status") == "working" for p in holders(snap, loop["workspace"], ref)
               if dispatch._tokens(p)["role"] == "reviewer"):
            continue
        out.append((ref, loop))
    return out


def now_due(st: dict, ref: str) -> None:
    """The PM's own-PR trigger (its round comment is posted): the next round opens on the next tick."""
    loop = st.get("loops", {}).get(ref)
    if not loop:
        raise ValueError("%s is not in a review loop — brief its first round with send-brief" % ref)
    cur = st.get("cursors", {}).get("pr:" + ref) or {}
    loop.update(due=1, head=cur.get("head"), held=False)


def fire(snap: dict, st: dict, now: float | None = None, opener=None) -> list[str]:
    """Open every due round; the PM hears one line per round."""
    log = []
    for ref, loop in due(snap, st, now):
        if _unfinished(snap, loop, ref):
            log.append("round %d on %s has no findings file yet — not reopened" % (loop["round"], ref))
            continue
        loop.pop("due", None)
        label = "review-%s" % ref.rsplit("#", 1)[-1]
        try:
            brief = next_brief(loop, ref, loop.get("head"))
            pane = (opener or _open)(snap, loop["workspace"], label, ref, brief)
        except Exception as exc:  # noqa: BLE001 — a failed open goes to the PM, never retried blind
            line = "[prometheus] auto round on %s failed to open: %s — open it yourself if it is due" % (ref, exc)
            log.append(line)
        else:
            loop.update(brief=brief, round=loop["round"] + 1)
            line = ("[prometheus] auto round %d on %s at %s opened in %s (%s). It checks whether a round is due "
                    "first. Veto: `rounds.sh hold %s` and close the tab." % (loop["round"], ref, (loop.get("head") or "?")[:10],
                                                                            label, pane, ref))
            log.append("auto round %d on %s" % (loop["round"], ref))
        try:
            pm = dispatch.route(snap, {"unit": loop["unit"], "role": "pm"})
            dispatch.enqueue(st, pm, line, unit=loop["unit"])
        except dispatch.RouteError as exc:
            log.append("auto round line unrouted: %s" % exc)
    return log


def findings_path(ref: str, n: int) -> str:
    return os.path.join(dispatch.state_dir(), "reviews", "%s-r%d.md" % (re.sub(r"[/#]", "-", ref), n))


def _unfinished(snap: dict, loop: dict, ref: str) -> bool:
    """A reviewer tab still holds the PR and its round wrote no findings file: a round in flight (or one a
    crash left behind) — closing it would kill it, so the next round waits."""
    held = [p for p in holders(snap, loop["workspace"], ref) if dispatch._tokens(p)["role"] == "reviewer"]
    return bool(held) and not os.path.exists(findings_path(ref, loop["round"]))


def _open(snap: dict, workspace_id: str, label: str, ref: str, brief: str) -> str:
    import units
    for p in holders(snap, workspace_id, ref):  # the finished round's tab: one round per session
        if dispatch._tokens(p)["role"] == "reviewer":
            tab = next((t.get("label") for t in snap.get("tabs", []) if t.get("tab_id") == p.get("tab_id")), None)
            if tab:
                units.close_tab(workspace_id, tab)
    pane = units.open_tab(workspace_id, label, "reviewer", pr=ref)
    units.send_brief(pane, brief, record_loop=False)
    return pane


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="rounds.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hold")
    h.add_argument("pr")
    h.add_argument("--off", action="store_true")
    sub.add_parser("list")
    sub.add_parser("next").add_argument("pr")
    a = ap.parse_args(argv)
    with dispatch.locked_state() as st:
        loops = st.setdefault("loops", {})
        if a.cmd == "list":
            print(json.dumps(loops, indent=1))
            return 0
        if a.pr not in loops:
            print("rounds: %s is not in a review loop" % a.pr, file=sys.stderr)
            return 1
        if a.cmd == "next":
            now_due(st, a.pr)
            print("%s: the next round opens on the dispatcher's next full tick (within a minute)" % a.pr)
            return 0
        loops[a.pr]["held"] = not a.off
        loops[a.pr].pop("due", None)
        print("%s %s" % (a.pr, "released: rounds open on new commits" if a.off else "held: no automatic rounds"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
