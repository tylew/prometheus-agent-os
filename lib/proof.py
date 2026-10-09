#!/usr/bin/env python3
# ---
# name: proof
# description: The build proof for one story, from git — every commit on each rung is tests (only test files) or code (none), never mixed; the tests each tests commit adds fail at that commit inside the test body (not at import or collection) and pass at the rung's head; every story scenario has a `Scenario: <name>` test; every failure mode names a test that exists or says why it cannot happen. Runs the package's registry scenario_run in throwaway detached worktrees. Writes <story_dir>/proof.json; report.sh --done refuses without a current, clean one.
# usage: proof.py run --story sc-<id> --worktree <abs> [--project <key>] [--scenarios <file>] | proof.py check --story sc-<id> --worktree <abs>
# ---
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env  # noqa: E402
import registry  # noqa: E402

SCENARIO = re.compile(r"^\s*Scenario(?: Outline)?:\s*(.+?)\s*$", re.M)
CANNOT = "cannot happen:"


def read(path: str) -> str:
    with open(path) as fh:
        return fh.read()


def git(wt: str, *args: str) -> str:
    return subprocess.run(["git", "-C", wt, *args], check=True, capture_output=True, text=True).stdout


def story_dir(story: str) -> str:
    sid = story if story.startswith("sc-") else "sc-%s" % story
    return os.path.join(env.state_dir(), "engine", "stories", sid)


def glob_re(pattern: str) -> re.Pattern:
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def packages(project: str) -> list[dict]:
    return registry.entry(project).get("packages", [])


def package_of(path: str, pkgs: list[dict]) -> dict | None:
    for p in pkgs:
        if any(glob_re(g).match(path) for g in p.get("tests", [])):
            return p
    return None


def parent(wt: str, branch: str, default: str) -> str:
    try:
        out = subprocess.run(["gt", "branch", "info", branch, "--no-interactive"], cwd=wt, check=True,
                             capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return default
    m = re.search(r"^Parent:\s*(\S+)", out, re.M)
    return m.group(1) if m else default


def rungs(wt: str, default: str) -> list[dict]:
    """The stack from the worktree's branch down to the default branch, bottom first."""
    out, branch = [], git(wt, "rev-parse", "--abbrev-ref", "HEAD").strip()
    while branch and branch != default and len(out) < 20:
        base = parent(wt, branch, default)
        commits = git(wt, "rev-list", "--reverse", "%s..%s" % (base, branch)).split()
        out.append({"branch": branch, "base": base, "head": git(wt, "rev-parse", branch).strip(),
                    "commits": commits})
        branch = base
    return out[::-1]


def changed(wt: str, sha: str) -> list[str]:
    return [l for l in git(wt, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha).splitlines() if l]


def classify(paths: list[str], pkgs: list[dict]) -> str:
    tests = [p for p in paths if package_of(p, pkgs)]
    return "tests" if tests and len(tests) == len(paths) else "code" if not tests else "mixed"


def parse(report: str, kind: str) -> dict[str, str]:
    """test id → passed / failed / error / skipped."""
    res = {}
    if kind == "junit":
        for case in ET.parse(report).getroot().iter("testcase"):
            tags = {c.tag for c in case}
            state = ("error" if "error" in tags else "failed" if "failure" in tags else
                     "skipped" if "skipped" in tags else "passed")
            res["%s::%s" % (case.get("classname", ""), case.get("name", ""))] = state
    else:
        data = json.loads(read(report))
        for f in data.get("testResults", []):
            if not f.get("assertionResults") and f.get("status") == "failed":
                res["%s::<suite>" % f["name"]] = "error"
            for a in f.get("assertionResults", []):
                st = a.get("status")
                res["%s::%s" % (f["name"], a.get("fullName"))] = (
                    "passed" if st == "passed" else "failed" if st == "failed" else "skipped")
    return res


def run_tests(wt: str, sha: str, files: list[str], pkg: dict, project: str) -> dict[str, str] | str:
    """Results of `files` at `sha` in a throwaway detached worktree, or the reason it could not run."""
    if not pkg.get("scenario_run") or not pkg.get("report"):
        return "package %s has no scenario_run / report in the registry" % pkg.get("name")
    base = os.path.join(env.state_dir(), "proof")
    os.makedirs(base, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="wt-%s-" % sha[:8], dir=base)
    os.rmdir(tmp)
    git(wt, "worktree", "add", "--detach", tmp, sha)
    try:
        try:
            import units
            units.link_worktree(tmp, project)
        except Exception:
            pass
        for rel in pkg.get("proof_links", []):
            src, dst = os.path.join(wt, rel), os.path.join(tmp, rel)
            if os.path.exists(src) and not os.path.lexists(dst) and os.path.isdir(os.path.dirname(dst)):
                os.symlink(src, dst)
        report = tmp + ".report"
        present = [f for f in files if os.path.exists(os.path.join(tmp, f))]
        if not present:
            return {}
        cmd = (pkg["scenario_run"].replace("<worktree>", shlex.quote(tmp))
               .replace("<tests>", " ".join(shlex.quote(os.path.join(tmp, f)) for f in present))
               .replace("<report>", shlex.quote(report)))
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=1800)
        if not os.path.exists(report):
            return "no report from %s at %s (exit %d): %s" % (pkg["name"], sha[:10], proc.returncode,
                                                              (proc.stderr or proc.stdout)[-300:].strip())
        res = parse(report, pkg["report"])
        os.unlink(report)
        return {k.replace(tmp + "/", ""): v for k, v in res.items()}
    finally:
        subprocess.run(["git", "-C", wt, "worktree", "remove", "--force", tmp], capture_output=True)


def scenarios_of(story: str, path: str | None) -> list[str]:
    if path:
        text = read(path)
    else:
        import tracker
        text = tracker.Tracker().get(story)["description"]
        m = re.search(r"^## Scenarios\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
        text = m.group(1) if m else text
    return SCENARIO.findall(text)


def failure_modes(path: str) -> list[tuple[str, str]]:
    """(mode, test) per table row of failure-modes.md; header and separator rows skipped."""
    rows = []
    if not os.path.exists(path):
        return rows
    for line in read(path).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or set(cells[0]) <= set("-: ") or cells[0].lower() == "mode":
            continue
        rows.append((cells[0], cells[2]))
    return rows


def prove(story: str, wt: str, project: str, scenarios_file: str | None = None) -> dict:
    ent = registry.entry(project)
    default = ent["repo"].get("default_branch", "main")
    pkgs = packages(project)
    problems, out = [], []
    stack = rungs(wt, default)
    if not stack:
        problems.append("no rung: the worktree's branch is %s" % default)
    for r in stack:
        rung = {"branch": r["branch"], "head": r["head"], "commits": [], "tests": []}
        added: dict[str, list[str]] = {}
        for sha in r["commits"]:
            paths = changed(wt, sha)
            kind = classify(paths, pkgs)
            rung["commits"].append({"sha": sha, "kind": kind})
            if kind == "mixed":
                problems.append("%s: commit %s mixes test and non-test files: %s"
                                % (r["branch"], sha[:10], ", ".join(paths)))
            if kind != "tests":
                continue
            for f in paths:
                added.setdefault(sha, []).append(f)
        touched: dict[str, dict] = {}
        for sha, files in added.items():
            by_pkg: dict[str, list[str]] = {}
            for f in files:
                p = package_of(f, pkgs)
                by_pkg.setdefault(p["name"], []).append(f)
                touched[f] = p
            for name, fs in by_pkg.items():
                pkg = next(p for p in pkgs if p["name"] == name)
                at = run_tests(wt, sha, fs, pkg, project)
                before = run_tests(wt, sha + "^", fs, pkg, project) if not isinstance(at, str) else {}
                if isinstance(at, str):
                    problems.append("%s: %s" % (r["branch"], at))
                    continue
                if isinstance(before, str):
                    before = {}
                for tid, state in sorted(at.items()):
                    if tid in before and before[tid] == state:
                        continue  # an existing test, untouched in outcome
                    red = {"passed": "held before"}.get(state, state)
                    rung["tests"].append({"id": tid, "tests_commit": sha, "red": red})
                    if state == "error":
                        problems.append("%s: %s errors at tests commit %s (import or collection) — "
                                        "land a skeleton first" % (r["branch"], tid, sha[:10]))
        by_pkg_head: dict[str, list[str]] = {}
        for f, p in touched.items():
            by_pkg_head.setdefault(p["name"], []).append(f)
        green: dict[str, str] = {}
        for name, fs in by_pkg_head.items():
            pkg = next(p for p in pkgs if p["name"] == name)
            res = run_tests(wt, r["head"], fs, pkg, project)
            if isinstance(res, str):
                problems.append("%s: %s" % (r["branch"], res))
            else:
                green.update(res)
        for t in rung["tests"]:
            t["head"] = green.get(t["id"], "missing")
            if t["head"] != "passed":
                problems.append("%s: %s is %s at the head" % (r["branch"], t["id"], t["head"]))
        out.append(rung)
    top = stack[-1]["head"] if stack else "HEAD"
    tests_text = ""
    if stack:
        files = [f for f in git(wt, "ls-tree", "-r", "--name-only", top).splitlines() if package_of(f, pkgs)]
        tests_text = "\n".join(git(wt, "show", "%s:%s" % (top, f)) for f in files[:2000])
    for name in scenarios_of(story, scenarios_file):
        if ("Scenario: %s" % name) not in tests_text:
            problems.append('scenario "%s" has no test carrying its Scenario: line' % name)
    for mode, test in failure_modes(os.path.join(story_dir(story), "failure-modes.md")):
        if test.lower().startswith(CANNOT):
            continue
        name = test.strip("`")
        if not name or name not in tests_text:
            problems.append('failure mode "%s": test "%s" not found' % (mode, name))
    return {"story": story, "worktree": wt, "at": int(time.time()), "rungs": out,
            "held_before": [t["id"] for r in out for t in r["tests"] if t["red"] == "held before"],
            "problems": problems}


def current(proof: dict, wt: str) -> list[str]:
    """Problems that make a saved proof unusable now: its own, and any rung whose branch moved since."""
    issues = list(proof.get("problems", []))
    for r in proof.get("rungs", []):
        try:
            head = git(wt, "rev-parse", r["branch"]).strip()
        except subprocess.CalledProcessError:
            issues.append("%s: branch gone" % r["branch"])
            continue
        if head != r["head"]:
            issues.append("%s moved since the proof (%s → %s): re-run proof.py" % (r["branch"], r["head"][:10],
                                                                                   head[:10]))
    if not proof.get("rungs"):
        issues.append("the proof covers no rung")
    return issues


def load(story: str) -> dict | None:
    path = os.path.join(story_dir(story), "proof.json")
    return json.loads(read(path)) if os.path.exists(path) else None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="proof.py")
    ap.add_argument("cmd", choices=("run", "check"))
    ap.add_argument("--story", required=True)
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--project")
    ap.add_argument("--scenarios")
    a = ap.parse_args(argv)
    wt = os.path.abspath(a.worktree)
    if a.cmd == "check":
        proof = load(a.story)
        issues = ["no proof.json — run proof.py run"] if proof is None else current(proof, wt)
        for i in issues:
            print(i)
        return 1 if issues else 0
    project = a.project or registry.repo_project(os.path.dirname(
        git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()))[0]
    if not project:
        print("no registry project owns %s — pass --project" % wt)
        return 2
    proof = prove(a.story, wt, project, a.scenarios)
    d = story_dir(a.story)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "proof.json"), "w") as fh:
        json.dump(proof, fh, indent=1)
    for p in proof["problems"]:
        print(p)
    for h in proof["held_before"]:
        print("held before (give the reason in the Scenario tests table): %s" % h)
    print("proof: %d rung(s), %d problem(s) → %s" % (len(proof["rungs"]), len(proof["problems"]),
                                                     os.path.join(d, "proof.json")))
    return 1 if proof["problems"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
