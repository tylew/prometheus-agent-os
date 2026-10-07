#!/usr/bin/env python3
# ---
# name: registry
# description: The one resolver over .claude/prometheus/ (workspace.json, projects/<key>.json, local.json) plus the live layer (Herdr workspace tokens, session pins). Two questions kept apart — active() = which product a session develops ($PROMETHEUS_PROJECT → the unit's project token → session pin → owner(cwd) → None, never a default); repo_project() = which checkout a git command mutates. Unreadable registry → None (project-code callers fail closed). check validates against registry.schema.json plus cross-file rules.
# usage: registry.py {active|repo [--cwd <dir>]|entry --key <key>|field <dotted.name> [--key <key>]|owner <path>|tracker [--key <key>]|runbook <key> <name>|unit|repos|projects|check} [--json]
# ---
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import env  # noqa: E402
import schema_lite  # noqa: E402

CONFIG_REL = os.path.join(".claude", "prometheus")
SCHEMA = os.path.join(LIB, "registry.schema.json")

_cache: dict = {}


# ---------------------------------------------------------------- loading

def config_dir(workspace: str | None = None) -> str:
    return os.path.join(workspace or env.workspace_root() or ".", CONFIG_REL)


def _read(path: str):
    mtime = os.path.getmtime(path)
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    with open(path) as fh:
        data = json.load(fh)
    _cache[path] = (mtime, data)
    return data


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def workspace_config(workspace: str | None = None) -> dict | None:
    try:
        return _read(os.path.join(config_dir(workspace), "workspace.json"))
    except (OSError, ValueError):
        return None


def local_config(workspace: str | None = None) -> dict:
    try:
        return _read(os.path.join(config_dir(workspace), "local.json"))
    except (OSError, ValueError):
        return {}


def projects(workspace: str | None = None) -> dict | None:
    """{key: entry} with local overrides applied, or None when the registry cannot be read.

    None is the fail-closed signal: "could not consult the registry", distinct from "no match".
    """
    d = os.path.join(config_dir(workspace), "projects")
    try:
        names = sorted(f for f in os.listdir(d) if f.endswith(".json"))
    except OSError:
        return None
    local = local_config(workspace).get("projects", {})
    out = {}
    try:
        for name in names:
            ent = _read(os.path.join(d, name))
            if isinstance(ent, dict) and isinstance(ent.get("repo"), dict) and ent["repo"].get("root"):
                key = ent.get("key") or name[:-5]
                out[key] = _merge(ent, local.get(key, {}))
    except (OSError, ValueError):
        return None
    return out or None


def entry(key: str, workspace: str | None = None) -> dict | None:
    return (projects(workspace) or {}).get(key)


def dig(ent: dict | None, dotted: str):
    cur = ent
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


# ------------------------------------------------------------ attribution

def _root(ent: dict) -> str:
    return (dig(ent, "repo.root") or "").strip("/")


def owner(path: str, workspace: str | None = None, registry: dict | None = None):
    """(key, entry, repo-relative path) for the entry owning `path`, by longest repo root.

    The workspace entry (root ".") never claims a path here — it would claim everything. Worktrees
    resolve through the checkout they were created from.
    """
    reg = registry if registry is not None else projects(workspace)
    if not reg:
        return None, None, None
    best = None
    for key, ent in reg.items():
        root = _root(ent)
        if root in ("", "."):
            continue
        m = re.search(re.escape("/" + root) + r"(?:/(.*))?$", path)
        if m and (best is None or len(root) > len(best[0])):
            best = (root, key, ent, m.group(1) or "")
    if best:
        return best[1], best[2], best[3]
    wt = re.search(r"(.*/\.worktrees/[^/]+)(?:/(.*))?$", path.rstrip("/"))
    if wt:
        try:
            common = subprocess.run(["git", "-C", wt.group(1), "rev-parse", "--git-common-dir"],
                                    capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            common = ""
        for key, ent in reg.items():
            root = _root(ent)
            if root not in ("", ".") and common and root in common:
                return key, ent, wt.group(2) or ""
    return None, None, None


# ----------------------------------------------------------------- live

def state_dir() -> str:
    return os.environ.get("PROMETHEUS_STATE_DIR") or os.path.expanduser("~/.claude/prometheus")


def pin_path(session_id: str) -> str:
    return os.path.join(state_dir(), "pins", "%s.json" % session_id)


def pinned(session_id: str | None = None) -> str | None:
    sid = session_id or os.environ.get("CLAUDE_SESSION_ID") or ""
    if not sid or "/" in sid:
        return None
    try:
        with open(pin_path(sid)) as fh:
            return json.load(fh).get("project") or None
    except (OSError, ValueError):
        return None


def unit() -> dict:
    """The current Herdr workspace's prometheus tokens ({} outside a unit or outside Herdr)."""
    ws = os.environ.get("HERDR_WORKSPACE_ID")
    if os.environ.get("HERDR_ENV") != "1" or not ws:
        return {}
    try:
        out = subprocess.run([os.environ.get("HERDR_BIN", "herdr"), "workspace", "get", ws],
                             capture_output=True, text=True, timeout=10)
        info = json.loads(out.stdout).get("result", {}).get("workspace", {})
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    toks = info.get("tokens") or {}
    return toks if toks.get("unit") else {}


def active(cwd: str | None = None, session_id: str | None = None, workspace: str | None = None):
    """(key, entry) for the product this session develops — first hit wins, no default:

      1. $PROMETHEUS_PROJECT     explicit override
      2. the unit's project      Herdr workspace token, for any session inside a unit
      3. the session pin         written by the edit guard on the first project edit
      4. owner(cwd)              a cwd inside a project checkout (never the workspace root)
      5. (None, None)            a writer asks; it never substitutes a guess
    """
    reg = projects(workspace)
    if not reg:
        return None, None
    for key in (os.environ.get("PROMETHEUS_PROJECT"), unit().get("project"), pinned(session_id)):
        if key and key in reg:
            return key, reg[key]
    key, ent, _ = owner(os.path.abspath(cwd or os.getcwd()), registry=reg)
    if key:
        return key, ent
    return None, None


def repo_project(cwd: str | None = None, workspace: str | None = None):
    """(key, entry) for the checkout `cwd` sits in — the workspace repo included (root ".")."""
    reg = projects(workspace)
    if not reg:
        return None, None
    here = os.path.abspath(cwd or os.getcwd())
    key, ent, _ = owner(here, registry=reg)
    if key:
        return key, ent
    ws = os.path.abspath(workspace or env.workspace_root(here) or "")
    if ws and (here == ws or here.startswith(ws + os.sep)):
        for k, e in reg.items():
            if _root(e) in ("", "."):
                return k, e
    return None, None


# --------------------------------------------------------------- lookups

def field(name: str, key: str | None = None, cwd: str | None = None, session_id: str | None = None,
          workspace: str | None = None, default=None):
    ent = entry(key, workspace) if key else active(cwd, session_id, workspace)[1]
    val = dig(ent, name)
    return default if val is None else val


def tracker(key: str | None = None, workspace: str | None = None) -> dict | None:
    ent = entry(key, workspace) if key else active(workspace=workspace)[1]
    ref = dig(ent, "tracker.ref")
    ws = workspace_config(workspace) or {}
    return (ws.get("trackers") or {}).get(ref) if ref else None


def runbook(key: str, name: str, workspace: str | None = None) -> str | None:
    ent = entry(key, workspace)
    if not ent or name not in (ent.get("runbooks") or []):
        return None
    path = os.path.join(config_dir(workspace), "projects", key, name)
    return path if os.path.isfile(path) else None


def repos(workspace: str | None = None) -> list[str]:
    """GitHub slugs of editable projects — what the dispatcher may poll."""
    return sorted({dig(e, "repo.slug") for e in (projects(workspace) or {}).values()
                   if e.get("access") == "editable" and dig(e, "repo.slug")})


def repo_projects(workspace: str | None = None) -> dict:
    out = {}
    for key, e in sorted((projects(workspace) or {}).items()):
        slug = dig(e, "repo.slug")
        if e.get("access") == "editable" and slug:
            out.setdefault(slug, key)
    return out


# ----------------------------------------------------------------- check

def check(workspace: str | None = None) -> list[str]:
    """Schema + cross-file rules. [] means the registry is sound."""
    schema = json.load(open(SCHEMA))
    base = config_dir(workspace)
    errs = []
    ws_path = os.path.join(base, "workspace.json")
    try:
        ws = json.load(open(ws_path))
        errs += ["workspace.json %s" % e for e in schema_lite.validate(ws, {"$ref": "#/$defs/workspace"}, schema)]
    except (OSError, ValueError) as exc:
        return ["workspace.json unreadable: %s" % exc]
    trackers = set((ws.get("trackers") or {}).keys())
    pdir = os.path.join(base, "projects")
    try:
        names = sorted(f for f in os.listdir(pdir) if f.endswith(".json"))
    except OSError:
        return errs + ["projects/ missing"]
    roots = {}
    for name in names:
        try:
            ent = json.load(open(os.path.join(pdir, name)))
        except (OSError, ValueError) as exc:
            errs.append("projects/%s unreadable: %s" % (name, exc))
            continue
        errs += ["projects/%s %s" % (name, e) for e in schema_lite.validate(ent, {"$ref": "#/$defs/project"}, schema)]
        key = ent.get("key")
        if key and key + ".json" != name:
            errs.append("projects/%s: key %r does not match the file name" % (name, key))
        ref = dig(ent, "tracker.ref")
        if ref and ref not in trackers:
            errs.append("projects/%s: tracker.ref %r is not a workspace tracker" % (name, ref))
        for rb in ent.get("runbooks") or []:
            if not os.path.isfile(os.path.join(pdir, key or name[:-5], rb)):
                errs.append("projects/%s: runbook %s missing" % (name, rb))
        root = _root(ent)
        if root in roots:
            errs.append("projects/%s: repo.root %r also claimed by %s" % (name, root, roots[root]))
        roots[root] = name
    try:
        local = json.load(open(os.path.join(base, "local.json")))
        errs += ["local.json %s" % e for e in schema_lite.validate(local, {"$ref": "#/$defs/local"}, schema)]
    except OSError:
        pass
    except ValueError as exc:
        errs.append("local.json unreadable: %s" % exc)
    return errs


# ------------------------------------------------------------------- CLI

def _out(val, as_json: bool = False) -> int:
    if val is None or val == "" or val == [] or val == {}:
        return 1
    if as_json or isinstance(val, (dict, list)):
        print(json.dumps(val, indent=2))
    else:
        print(val)
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="registry.py")
    ap.add_argument("command", choices=["active", "repo", "entry", "field", "owner", "tracker", "runbook",
                                        "unit", "repos", "projects", "check"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--key")
    ap.add_argument("--cwd")
    ap.add_argument("--workspace")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    ws = a.workspace
    if a.command == "check":
        errs = check(ws)
        for e in errs:
            print(e)
        return 1 if errs else 0
    if a.command == "active":
        key, ent = active(a.cwd, workspace=ws)
        return _out(ent if a.json else key)
    if a.command == "repo":
        key, ent = repo_project(a.cwd, ws)
        return _out(ent if a.json else key)
    if a.command == "entry":
        key = a.key or active(a.cwd, workspace=ws)[0]
        return _out(entry(key, ws) if key else None)
    if a.command == "field":
        if not a.args:
            ap.error("field needs a name")
        return _out(field(a.args[0], key=a.key, cwd=a.cwd, workspace=ws), a.json)
    if a.command == "owner":
        if not a.args:
            ap.error("owner needs a path")
        key, _ent, rel = owner(os.path.abspath(a.args[0]), ws)
        return _out({"project": key, "relpath": rel} if a.json and key else key)
    if a.command == "tracker":
        return _out(tracker(a.key, ws))
    if a.command == "runbook":
        if len(a.args) != 2:
            ap.error("runbook needs <key> <name>")
        return _out(runbook(a.args[0], a.args[1], ws))
    if a.command == "unit":
        return _out(unit())
    if a.command == "repos":
        return _out(repos(ws))
    if a.command == "projects":
        return _out(sorted((projects(ws) or {}).keys()))
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception:
        sys.exit(1)
