#!/usr/bin/env python3
# ---
# name: e2e
# description: Tier-3 plumbing e2e — in a throwaway prom-test-* workspace with its own state dir (never the operator's units): a unit whose PM starts through `herdr agent start` (Haiku), its brief lands, a queued message is delivered by a dispatcher tick, the restore image records the unit, the workspace is closed under it and `restore` brings it back on the same session. Everything it opened is closed and its state dir removed, pass or fail.
# usage: e2e.py [--keep]   (exit 1 on any failed step; --keep leaves the workspace and state for inspection)
# ---
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="e2e.py")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args(argv)
    if os.environ.get("HERDR_ENV") != "1":
        print("e2e: needs to run inside Herdr", file=sys.stderr)
        return 2
    state = tempfile.mkdtemp(prefix="prom-e2e-", dir=os.path.expanduser("~/.local/state"))
    os.environ.update(PROMETHEUS_STATE_DIR=state, PROMETHEUS_EXTERNAL="0", PROMETHEUS_FILTER="(?!)", PROMETHEUS_TEST_UNITS="1",
                      PROMETHEUS_KB_ROOT=os.path.join(state, "kb"))
    import dispatch
    import units
    name = "prom-test-e2e-%d" % int(time.time())
    opened, results = [], []

    def step(label: str, ok: bool, detail: str = "") -> bool:
        results.append((label, ok))
        print("%s %s%s" % ("✔" if ok else "✘", label, (" — " + detail) if detail else ""), flush=True)
        return ok

    try:
        out = units.create(name, "story", "prometheus", ["sc-0"], [], claude_args=["--model", "haiku"])
        opened.append(out["workspace"])
        pm = out["pane"]
        step("unit created and PM started", dispatch.pane(dispatch.snapshot(), pm) is not None, pm)
        units.set_tokens(out["workspace"], stage="design", add_prs=["o/r#1"])
        row = next((r for r in units.list_units() if r["unit"] == name), {})
        step("unit tokens set (stage, prs)", (row.get("stage"), row.get("prs")) == ("design", "o/r#1"), str(row))
        many = ["o/r#%d" % n for n in range(1000, 1010)]
        units.set_tokens(out["workspace"], prs=",".join(many))
        raw = units.hz.call("api", "snapshot").get("snapshot", {})
        token = next((w.get("tokens") or {} for w in raw.get("workspaces", [])
                      if w.get("workspace_id") == out["workspace"]), {}).get("prs", "")
        row = next((r for r in units.list_units() if r["unit"] == name), {})
        step("10 PRs: token ≤80 whole entries, unit row holds all",
             len(token) <= 80 and set(token.split(",")) <= set(many) and row.get("prs") == ",".join(many),
             "token=%r row=%r" % (token, row.get("prs")))
        brief = os.path.join(state, "brief.md")
        with open(brief, "w") as fh:
            fh.write("Plumbing e2e. Reply with the single word OK and do nothing else.\n")
        step("brief landed (a turn started)", units.send_brief(pm, brief).startswith("landed"))
        units.hz.call("agent", "wait", pm, "--until", "idle", "--until", "done", "--timeout", "120000", timeout=130)
        with dispatch.locked_state() as st:
            dispatch.enqueue(st, pm, "[prometheus] e2e: reply OK again")
        report = dispatch.tick(external=False)
        step("queued line delivered by a tick", pm in report["delivered"], str(report["delivered"]))
        units.hz.call("agent", "wait", pm, "--until", "idle", "--until", "done", "--timeout", "120000", timeout=130)
        dispatch.tick(external=False)
        with dispatch.locked_state() as st:
            img = st.get("image", {}).get(name, {})
        session = next((x.get("session") for x in img.get("agents", []) if x["tokens"].get("role") == "pm"), None)
        step("restore image holds the unit and its PM session", bool(session), str(session))
        units._h("workspace", "close", out["workspace"])
        opened.remove(out["workspace"])
        back = units.restore_all(only=[name])
        if back:
            opened.append(back[0]["workspace"])
        step("restore brought the unit back on its session", bool(back) and back[0]["back"] == ["pm"],
             str(back[0] if back else "nothing restored"))
        if back:
            got = None
            for _ in range(30):  # Herdr reports the resumed session a moment after the agent is up
                snap = dispatch.snapshot()
                p = next((x for x in snap.get("panes", []) if x.get("workspace_id") == back[0]["workspace"]
                          and dispatch._tokens(x).get("role") == "pm"), {})
                got = dispatch.session_of(p)
                if got:
                    break
                time.sleep(1)
            step("restored PM runs the same session", got == session, got or "not reported in 30s")
    except Exception as exc:  # noqa: BLE001 — any failure is a red step, and cleanup still runs
        step("e2e aborted", False, "%s: %s" % (type(exc).__name__, exc))
    finally:
        if not a.keep:
            for ws in opened:
                try:
                    units._h("workspace", "close", ws)
                except Exception:  # noqa: BLE001
                    print("e2e: could not close %s — close it by hand" % ws, file=sys.stderr)
            shutil.rmtree(state, ignore_errors=True)
        else:
            print("e2e: kept %s and %s" % (", ".join(opened), state))
    failed = [l for l, ok in results if not ok]
    print("e2e: %d/%d steps passed" % (len(results) - len(failed), len(results)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
