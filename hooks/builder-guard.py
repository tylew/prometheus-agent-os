#!/usr/bin/env python3
# ---
# name: builder-guard
# description: PreToolUse for the builder subagent only (hook input agent_type ends in "builder") — denies an edit to a test file (any registry package's `tests` globs, matched from the file's git worktree root), to a story's idr.md or failure-modes.md, and any git / gt command other than status, diff, log and show. Every other caller passes untouched.
# usage: hooks.json → PreToolUse (Edit|Write|MultiEdit|NotebookEdit, Bash)
# ---
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))

GIT_RE = re.compile(r"(?:^|[;&|(]\s*|\bxargs\s+)(?:\S+=\S+\s+)*(git|gt)\b((?:\s+-C\s+\S+)?)\s+(\S+)")
GIT_READS = {"status", "diff", "log", "show", "rev-parse", "ls-files", "grep", "blame"}
STORY_FILES = ("idr.md", "failure-modes.md")


def _deny(msg: str) -> int:
    sys.stderr.write("builder: " + msg + "\n")
    return 2


def _root(path: str) -> str | None:
    d = os.path.dirname(os.path.abspath(path))
    while d and d != os.path.dirname(d):
        if os.path.exists(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    return None


def test_globs() -> list[str]:
    import registry
    globs = []
    for ent in (registry.projects() or {}).values():
        for pkg in ent.get("packages", []) or []:
            globs.extend(pkg.get("tests", []))
    return globs


def is_test_file(path: str) -> bool:
    import proof
    root = _root(path)
    if not root:
        return False
    rel = os.path.relpath(os.path.abspath(path), root)
    return any(proof.glob_re(g).match(rel) for g in test_globs())


def check(data: dict) -> str | None:
    """The reason to deny, or None."""
    if not str(data.get("agent_type") or "").endswith("builder"):
        return None
    tool, inp = data.get("tool_name"), data.get("tool_input") or {}
    if tool == "Bash":
        for m in GIT_RE.finditer(inp.get("command", "")):
            if m.group(3) not in GIT_READS:
                return "%s %s is the implementor's — return your diff and results instead" % (m.group(1), m.group(3))
        return None
    path = inp.get("file_path") or inp.get("notebook_path") or ""
    if not path:
        return None
    if os.path.basename(path) in STORY_FILES:
        return "%s is the implementor's — a needed change goes back as a stop block" % os.path.basename(path)
    if is_test_file(path):
        return "%s is a test file: make the tests pass without editing them; a wrong test goes back as a " \
               "stop block" % path
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    reason = check(data)
    return _deny(reason) if reason else 0


if __name__ == "__main__":
    sys.exit(main())
