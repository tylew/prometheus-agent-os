#!/usr/bin/env python3
# ---
# name: project-guard
# description: PreToolUse on Edit/Write/MultiEdit/NotebookEdit — edits inside a project checkout (repos/, samples/, .worktrees/) are denied when the registry cannot be read, when no entry claims the path, on a reference clone, outside the project's owned_paths, or in a second project once the session is pinned (first project edit pins it). SessionStart — announces the active project and reports any registry check errors. Workspace paths are never gated; Bash writes are not seen.
# usage: hooks.json → SessionStart, PreToolUse (Edit|Write|MultiEdit|NotebookEdit)
# ---
from __future__ import annotations

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import registry  # noqa: E402

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
PROJECT_PATH_RE = re.compile(r"/(?:repos|samples|\.worktrees)/")
STALE_PIN_SECS = 3 * 24 * 3600


def _deny(msg: str) -> int:
    sys.stderr.write(msg + "\n")
    return 2


def _pin(sid: str, key: str) -> None:
    path = registry.pin_path(sid)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w") as fh:
            json.dump({"session_id": sid, "project": key, "pinned_at": int(time.time())}, fh)
        os.replace(path + ".tmp", path)
    except OSError:
        pass


def _gc() -> None:
    d = os.path.dirname(registry.pin_path("x"))
    try:
        now = time.time()
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if now - os.path.getmtime(p) > STALE_PIN_SECS:
                os.remove(p)
    except OSError:
        pass


def guard(payload: dict, sid: str) -> int:
    ti = payload.get("tool_input") or {}
    raw = ti.get("file_path") or ti.get("notebook_path") or ""
    if not raw:
        return 0
    cwd = payload.get("cwd") or os.getcwd()
    target = raw if os.path.isabs(raw) else os.path.normpath(os.path.join(cwd, raw))
    if not PROJECT_PATH_RE.search(target):
        return 0
    reg = registry.projects()
    if reg is None:
        return _deny("🔒 The prometheus registry (.claude/prometheus/) is missing or unreadable, so `%s` cannot "
                     "be attributed to a project. Edits to project checkouts are denied until "
                     "`registry.py check` is clean; workspace paths are unaffected." % target)
    key, ent, rel = registry.owner(target, registry=reg)
    if not key:
        return _deny("🔒 `%s` is inside a project checkout no registry entry claims. Register it "
                     "(.claude/prometheus/projects/<key>.json), or leave it read-only." % target)
    if ent.get("access") != "editable":
        return _deny("🔒 `%s` belongs to reference clone '%s' — read it freely, never edit it." % (target, key))
    owned = [p.strip("/") for p in ent.get("owned_paths") or [] if p]
    if owned and rel and not any(rel == p or rel.startswith(p + "/") for p in owned):
        return _deny("🔒 Out of scope for '%s': `%s` is outside its owned paths (%s). Editing it is a "
                     "cross-cutting change — surface the path to the operator and get explicit go-ahead."
                     % (key, rel, ", ".join(owned)))
    pinned = registry.pinned(sid)
    unit_project = registry.unit().get("project")
    expected = pinned or unit_project
    if expected and expected != key:
        return _deny("🔒 Cross-project edit: this session works '%s', but `%s` belongs to '%s'. Reading it is "
                     "fine; editing it is not. A deliberate switch clears the pin (%s)."
                     % (expected, target, key, registry.pin_path(sid)))
    if not pinned:
        _pin(sid, key)
    return 0


def announce(sid: str) -> int:
    pinned = registry.pinned(sid)
    reg = registry.projects() or {}
    unit_project = registry.unit().get("project")
    if pinned or unit_project:
        msg = "Active project: **%s** (%s). Edits to another project's code are blocked; reading it is fine." % (
            pinned or unit_project, "pinned this session" if pinned else "this unit's project")
    else:
        editable = sorted(k for k, v in reg.items() if v.get("access") == "editable")
        msg = ("Active project: **none yet** — the first edit to a project's tree pins the session. Editable: %s. "
               "Reference clones are never editable. The guard sees Edit/Write only; Bash writes are unchecked."
               % (", ".join(editable) or "none registered"))
    errs = registry.check()
    if errs:
        msg += "\n\nRegistry check failed (%d) — project edits fail closed until fixed:\n- %s" % (
            len(errs), "\n- ".join(errs[:8]))
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}))
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    sid = payload.get("session_id") or ""
    if not sid or "/" in sid:
        return 0
    event = payload.get("hook_event_name") or ""
    _gc()
    if event == "SessionStart":
        try:
            return announce(sid)
        except Exception:
            return 0
    if event == "PreToolUse" and payload.get("tool_name") in EDIT_TOOLS:
        try:
            return guard(payload, sid)
        except Exception:
            return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
