#!/usr/bin/env python3
# ---
# name: migrate_team_json
# description: One-way migration of .claude/voltus-besstie/team.json into .claude/prometheus/ — workspace.json, projects/<key>.json, runbooks copied from .claude/voltus-besstie/projects/<key>/*.md, and every _comment/_note prose key moved into a registry-notes.md runbook. Dry-run by default (prints the plan and validates the result); --write refuses to overwrite an existing registry unless --force. team.json is never modified.
# usage: migrate_team_json.py [--write [--force]] [--workspace <dir>] [--json]
# ---
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import env  # noqa: E402
import registry  # noqa: E402

SOURCE_REL = os.path.join(".claude", "voltus-besstie")
NOTES = "registry-notes.md"
KNOWN = {"description", "repo", "root", "access", "owned_paths", "vcs", "pr_title_prefix", "commit_trailer",
         "tracker", "specs", "vault_area", "native_config", "validation", "deploy", "envs", "migrations",
         "review_docs", "approval_gated_checks"}


def state_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def default_branch(workspace: str, root: str) -> str | None:
    path = os.path.join(workspace, root)
    if not os.path.isdir(path):
        return None
    try:
        out = subprocess.run(["git", "-C", path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    ref = out.stdout.strip()
    return ref.split("/", 1)[1] if out.returncode == 0 and "/" in ref else None


def collect_notes(node, path: str, out: list) -> None:
    """Every _comment / _note-style key anywhere in a node → (path, text)."""
    if isinstance(node, dict):
        for k, v in node.items():
            p = "%s.%s" % (path, k) if path else k
            if k.startswith("_") and isinstance(v, str):
                out.append((p, v))
            else:
                collect_notes(v, p, out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            collect_notes(v, "%s[%d]" % (path, i), out)


def workspace_json(team: dict, warnings: list) -> tuple[dict, list]:
    notes: list = []
    for k, v in team.items():
        if k != "projects":
            collect_notes({k: v}, "", notes)
    wf = team.get("workflow") or {}
    states, intake = [], None
    for s in wf.get("states", []):
        gate = s.get("gate", "")
        if gate.upper().startswith("RETIRED"):
            continue
        st = {"key": state_key(s["name"]), "id": str(s["id"]), "name": s["name"]}
        if gate:
            st["gate"] = gate
        states.append(st)
        if (wf.get("intake_state") or {}).get("id") == s["id"]:
            intake = st["key"]
    shortcut = {"kind": "shortcut",
                "org_slug": (team.get("shortcut") or {}).get("org_slug", ""),
                "team_id": (team.get("team") or {}).get("team_id", ""),
                "team_name": (team.get("team") or {}).get("name", ""),
                "workflow": {"id": str(wf.get("id", "")), "name": wf.get("name", ""),
                             "intake": intake or (states[0]["key"] if states else "backlog"), "states": states},
                "labels": team.get("labels", []),
                "story_types": ["feature", "bug", "chore"],
                "estimate_scale": [1, 2, 3, 5, 8], "split_at": 8,
                "catch_all_epic": (team.get("epics") or {}).get("default_catch_all"),
                "docs_folder": (team.get("docs") or {}).get("folder")}
    op = {k: v for k, v in (team.get("operator") or {}).items() if not k.startswith("_")}
    if "default_project" in team:
        warnings.append("default_project %r dropped: prometheus never falls back to a default" % team["default_project"])
    return {"operator": op, "trackers": {"shortcut": shortcut, "operator": {"kind": "operator"}}}, notes


def project_json(key: str, src: dict, team: dict, workspace: str, warnings: list) -> tuple[dict, list]:
    notes: list = []
    collect_notes(src, "", notes)
    root = src["root"]
    ent = {"key": key, "description": src.get("description", ""), "access": src.get("access", "reference"),
           "repo": {"root": root}}
    if src.get("repo"):
        ent["repo"]["slug"] = src["repo"]
    branch = default_branch(workspace, root)
    if branch:
        ent["repo"]["default_branch"] = branch
        if ent["access"] == "reference":
            ent["repo"]["pin"] = "origin/%s" % branch
    if src.get("owned_paths"):
        ent["owned_paths"] = src["owned_paths"]
    if src.get("vcs"):
        ent["vcs"] = {"tool": src["vcs"]}
        for k in ("pr_title_prefix", "commit_trailer"):
            if src.get(k):
                ent["vcs"][k] = src[k]
    tr = src.get("tracker") or {}
    if tr.get("mode") == "shortcut":
        ent["tracker"] = {"ref": "shortcut", "gates": "full"}
        if tr.get("tag"):
            ent["tracker"]["tag"] = tr["tag"]
        team_id = (team.get("team") or {}).get("team_id")
        if tr.get("team_id") and tr["team_id"] != team_id:
            warnings.append("%s: tracker.team_id %s differs from the workspace team; dropped" % (key, tr["team_id"]))
    elif tr.get("mode") == "operator":
        ent["tracker"] = {"ref": "operator", "gates": "operator"}
    docs = {k: src[k] for k in ("specs", "vault_area", "native_config") if src.get(k)}
    if " — " in docs.get("native_config", ""):
        path, prose = docs["native_config"].split(" — ", 1)
        docs["native_config"] = path.strip()
        notes.append(("native_config", prose))
    if docs:
        ent["docs"] = docs
    val = src.get("validation") or {}
    pkgs = []
    if isinstance(val.get("commands"), list):
        pkgs.append({"name": key, "validate": val["commands"]})
    for name, sub in val.items():
        if isinstance(sub, dict) and isinstance(sub.get("commands"), list):
            pkg = {"name": name, "validate": sub["commands"]}
            if sub.get("path"):
                pkg["path"] = sub["path"]
            pkgs.append(pkg)
    if pkgs:
        ent["packages"] = pkgs
    if src.get("deploy"):
        text = src["deploy"]
        notes.append(("deploy", text))
        ent["deploy"] = {"tool": re.split(r"[\s—-]+", text.strip(), 1)[0]}
        if src.get("envs"):
            ent["deploy"]["envs"] = {k: v for k, v in src["envs"].items() if not k.startswith("_")}
        if "operator" in text.lower() and "prod" in text.lower():
            ent["deploy"]["prod_requires_operator"] = True
    if src.get("migrations"):
        text = src["migrations"]
        notes.append(("migrations", text))
        tool, _, rest = text.partition("—")
        tool = tool.strip()
        if tool.lower() != "none":
            ent["migrations"] = {"tool": tool}
            path = rest.strip().split()[0] if rest.strip() else ""
            if "/" in path:
                ent["migrations"]["path"] = path
        else:
            ent["migrations"] = None
    review = {}
    if src.get("review_docs"):
        review["docs"] = [{"path": d["path"], "applies_to": d["applies_to"]} for d in src["review_docs"]]
    if src.get("approval_gated_checks"):
        review["approval_gated_checks"] = src["approval_gated_checks"]
    if review:
        ent["review"] = review
    extra = {k: str(v) for k, v in src.items() if k not in KNOWN and not k.startswith("_") and isinstance(v, (str, int))}
    if extra:
        ent["extra"] = extra
    for k, v in src.items():
        if k not in KNOWN and not k.startswith("_") and not isinstance(v, (str, int)):
            warnings.append("%s: field %r (%s) not mapped" % (key, k, type(v).__name__))
    return ent, notes


def notes_md(title: str, notes: list) -> str:
    lines = ["# %s — registry notes" % title, "",
             "Prose moved out of the registry by the team.json migration. The registry holds facts; this file "
             "holds the why and the traps behind them.", ""]
    for path, text in notes:
        lines += ["## `%s`" % path, "", text.strip(), ""]
    return "\n".join(lines)


def plan(workspace: str) -> dict:
    team = json.load(open(os.path.join(workspace, SOURCE_REL, "team.json")))
    warnings: list = []
    ws, ws_notes = workspace_json(team, warnings)
    files = {"workspace.json": json.dumps(ws, indent=2) + "\n"}
    if ws_notes:
        files["workspace-notes.md"] = notes_md("Workspace", ws_notes)
    copies = []
    for key, src in (team.get("projects") or {}).items():
        if not isinstance(src, dict) or not src.get("root"):
            continue
        ent, notes = project_json(key, src, team, workspace, warnings)
        runbooks = []
        src_dir = os.path.join(workspace, SOURCE_REL, "projects", key)
        if os.path.isdir(src_dir):
            for f in sorted(os.listdir(src_dir)):
                if f.endswith(".md"):
                    copies.append((os.path.join(src_dir, f), os.path.join("projects", key, f)))
                    runbooks.append(f)
        if notes:
            files[os.path.join("projects", key, NOTES)] = notes_md(key, notes)
            runbooks.append(NOTES)
        if runbooks:
            ent["runbooks"] = sorted(runbooks)
        if ent.get("deploy") and "deploy.md" in runbooks:
            ent["deploy"]["runbook"] = "deploy.md"
        for pkg in ent.get("packages", []):
            if NOTES in runbooks:
                pkg["runbook"] = NOTES
        files[os.path.join("projects", "%s.json" % key)] = json.dumps(ent, indent=2) + "\n"
    return {"files": files, "copies": copies, "warnings": warnings}


def materialise(p: dict, dest: str) -> None:
    for rel, text in p["files"].items():
        path = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
    for src, rel in p["copies"]:
        path = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copyfile(src, path)


def validate(p: dict) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        materialise(p, os.path.join(tmp, registry.CONFIG_REL))
        registry._cache.clear()
        return registry.check(tmp)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="migrate_team_json.py")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workspace")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    workspace = a.workspace or env.workspace_root()
    p = plan(workspace)
    errors = validate(p)
    if a.json:
        print(json.dumps({"files": sorted(p["files"]), "copies": [r for _, r in p["copies"]],
                          "warnings": p["warnings"], "errors": errors}, indent=2))
    else:
        print("would write %d files, copy %d runbooks into %s" % (len(p["files"]), len(p["copies"]), registry.CONFIG_REL))
        for rel in sorted(list(p["files"]) + [r for _, r in p["copies"]]):
            print("  " + rel)
        for w in p["warnings"]:
            print("warning: " + w)
        for e in errors:
            print("error: " + e)
        print("schema check: %s" % ("clean" if not errors else "%d error(s)" % len(errors)))
    if errors:
        return 1
    if a.write:
        dest = os.path.join(workspace, registry.CONFIG_REL)
        if os.path.isdir(os.path.join(dest, "projects")) and not a.force:
            print("refusing: %s already holds a registry (--force to overwrite)" % dest, file=sys.stderr)
            return 2
        materialise(p, dest)
        print("written to %s" % dest)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
