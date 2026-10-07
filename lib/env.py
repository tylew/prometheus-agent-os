#!/usr/bin/env python3
# ---
# name: env
# description: Resolve the workspace root once for every prometheus script — $WORKSPACE if set, else the git toplevel holding this plugin (when the plugin lives in a workspace checkout), else the git toplevel of the cwd. Exit 1 with empty stdout when unresolvable.
# usage: env.py [workspace]
# ---
from __future__ import annotations

import os
import subprocess
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _toplevel(path: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def workspace_root(cwd: str | None = None) -> str | None:
    env = os.environ.get("WORKSPACE")
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    top = _toplevel(PLUGIN_ROOT)
    if top and os.path.isdir(os.path.join(top, "plugins", "prometheus")):
        return top
    return _toplevel(cwd or os.getcwd())


def main(argv: list[str]) -> int:
    if argv and argv[0] != "workspace":
        print("usage: env.py [workspace]", file=sys.stderr)
        return 2
    root = workspace_root()
    if not root:
        return 1
    print(root)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
