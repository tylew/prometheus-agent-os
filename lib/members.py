#!/usr/bin/env python3
# ---
# name: members
# description: A unit's full stories / prs / stages lists. Herdr cuts every token value at 80 characters, so the lists live in <state>/members.json keyed by unit name; the workspace tokens carry a display copy cut at a whole entry, and every snapshot is overlaid with the full lists before anyone reads it.
# usage: imported (import members)
# ---
from __future__ import annotations

import contextlib
import fcntl
import json
import os

import env

LISTS = ("stories", "prs", "stages")
TOKEN_MAX = 80


def _path() -> str:
    d = env.state_dir()
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "members.json")


def load() -> dict:
    try:
        with open(_path()) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@contextlib.contextmanager
def _locked():
    with open(_path() + ".lock", "a+") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        data = load()
        yield data
        tmp = _path() + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, _path())


def save(unit: str, values: dict) -> None:
    keep = {k: v for k, v in values.items() if k in LISTS and v is not None}
    if unit and keep:
        with _locked() as data:
            data.setdefault(unit, {}).update(keep)


def forget(unit: str) -> None:
    with _locked() as data:
        data.pop(unit, None)


def display(value: str) -> str:
    """The token copy: whole entries only, at most TOKEN_MAX characters."""
    out = ""
    for part in [v for v in (value or "").split(",") if v]:
        nxt = part if not out else out + "," + part
        if len(nxt) > TOKEN_MAX:
            break
        out = nxt
    return out


def overlay(snap: dict) -> dict:
    """Give every unit workspace its full lists (in place); a unit with no record keeps its tokens."""
    data = load()
    if not data:
        return snap
    for w in snap.get("workspaces", []):
        t = w.get("tokens")
        rec = data.get((t or {}).get("unit")) if isinstance(t, dict) else None
        if rec:
            t.update({k: v for k, v in rec.items() if k in LISTS})
    return snap
