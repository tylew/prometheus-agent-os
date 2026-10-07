# ---
# name: map.activity
# description: Agent activity over time for the map's activity plot — Claude session transcripts (found by Herdr's agent_session id, subagents included) tailed incrementally; panes without a transcript are sampled while working. Read-only.
# usage: imported (from map import activity)
# ---
# Ported from Horchestra's activity.py (https://github.com/SimoneDaniotti/horchestra),
# MIT License, Copyright (c) 2026 Simone Daniotti.
from __future__ import annotations

import datetime
import glob
import json
import os
import time

READ_TAIL = 8 << 20  # bytes read back from a transcript the first time it is seen
KEEP_SECONDS = 24 * 3600  # history older than this is dropped
LOCATE_RETRY = 30.0  # seconds before looking again for a transcript not found
SAMPLE_EVERY = 2.0  # seconds between status samples for agents without transcripts
WINDOWS = [600, 1800, 3600, 3 * 3600, 12 * 3600]  # plot windows, cycled with [ and ]
LEVELS = " ▁▂▃▄▅▆▇█"


def parse_time(text):
    """Epoch seconds from an ISO-8601 timestamp, or None."""
    if not isinstance(text, str) or not text:
        return None
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def claude_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def locate(session, claude_root=None):
    """The Claude session's main transcript, or None."""
    if not session or "/" in session or session.startswith("."):
        return None
    root = claude_root or claude_dir()
    hits = glob.glob(os.path.join(glob.escape(root), "projects", "*", glob.escape(session) + ".jsonl"))
    return max(hits, key=os.path.getmtime) if hits else None


def subagent_files(main):
    """Claude subagent transcripts that belong to the session in `main`."""
    if not main:
        return []
    folder = os.path.join(main[: -len(".jsonl")], "subagents")
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return [os.path.join(folder, n) for n in sorted(names) if n.endswith(".jsonl")]


class Transcript:
    """One JSONL file, read incrementally."""

    def __init__(self, path):
        self.path = path
        self.offset = None  # None until the first read
        self.times = []

    def poll(self):
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return
        if self.offset is not None and size < self.offset:
            self.offset, self.times = None, []  # replaced or truncated: start over
        start = max(0, size - READ_TAIL) if self.offset is None else self.offset
        if start >= size:
            self.offset = size
            return
        try:
            with open(self.path, "rb") as fh:
                fh.seek(start)
                data = fh.read(size - start)
        except OSError:
            return
        end = data.rfind(b"\n")
        if end < 0:
            self.offset = start
            return
        lines = data[: end + 1].split(b"\n")
        if self.offset is None and start > 0:
            lines = lines[1:]  # began mid-line
        self.offset = start + end + 1
        for line in lines:
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
            except ValueError:
                continue
            if isinstance(doc, dict) and doc.get("type") == "assistant":
                stamp = parse_time(doc.get("timestamp"))
                if stamp is not None:
                    self.times.append(stamp)


class Activity:
    """Activity times per pane, from Claude transcripts or status samples."""

    def __init__(self, clock=time.time, claude_root=None):
        self.clock = clock
        self.claude_root = claude_root
        self.sources = {}  # session -> {"main": path|None, "looked": t, "files": {path: Transcript}}
        self.samples = {}  # pane_id -> [times sampled while working]
        self.session_of = {}  # pane_id -> session

    def update(self, panes):
        now = self.clock()
        for pane in panes:
            pane_id, kind = pane.get("pane_id"), pane.get("agent")
            if not pane_id or not kind:
                continue
            ref = pane.get("agent_session") if isinstance(pane.get("agent_session"), dict) else {}
            session = ref.get("value") if ref.get("kind") == "id" else None
            if kind == "claude" and session:
                self.session_of[pane_id] = session
                self._poll(session, now)
            elif pane.get("agent_status") == "working":
                times = self.samples.setdefault(pane_id, [])
                if not times or now - times[-1] >= SAMPLE_EVERY:
                    times.append(now)
        cutoff = now - KEEP_SECONDS
        for times in self.samples.values():
            while times and times[0] < cutoff:
                times.pop(0)

    def _poll(self, session, now):
        src = self.sources.setdefault(session, {"main": None, "looked": None, "files": {}})
        if src["main"] is None and (src["looked"] is None or now - src["looked"] >= LOCATE_RETRY):
            src["looked"] = now
            src["main"] = locate(session, self.claude_root)
        if src["main"] is None:
            return
        for path in [src["main"], *subagent_files(src["main"])]:
            if path not in src["files"]:
                src["files"][path] = Transcript(path)
            src["files"][path].poll()

    def has_history(self, pane_id):
        src = self.sources.get(self.session_of.get(pane_id))
        return bool(src and src["main"]) or bool(self.samples.get(pane_id))

    def times(self, pane_id):
        src = self.sources.get(self.session_of.get(pane_id))
        if src and src["main"]:
            out = []
            for transcript in src["files"].values():
                out.extend(transcript.times)
            return out
        return list(self.samples.get(pane_id, []))


def buckets(times, now, window, count):
    """Activity counts in `count` equal slices of the last `window` seconds, aligned to slice width."""
    count = max(1, count)
    width = window / count
    end = (now // width + 1) * width
    start = end - width * count
    out = [0] * count
    for stamp in times:
        if start <= stamp < end:
            out[min(count - 1, int((stamp - start) // width))] += 1
    return out


def sparkline(counts, peak):
    """One character per slice; any nonzero slice shows at least the lowest bar."""
    top = len(LEVELS) - 1
    if peak <= 0:
        return " " * len(counts)
    return "".join(LEVELS[0 if c <= 0 else max(1, min(top, -(-c * top // peak)))] for c in counts)


def window_label(seconds):
    return f"{seconds // 3600}h" if seconds >= 3600 else f"{seconds // 60}m"
