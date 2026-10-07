# ---
# name: map.app
# description: The prometheus map's curses front end — the primary view and navigation: header stats top-right (dispatcher, agents, status counts, needs-you, proposals, held), one drill-down level at a time (seat → units · unit PM → its agents · seat → control), a live preview of the selected agent (a unit previews its PM) mirrored from `herdr pane read --ansi`, and an interact mode that forwards keystrokes to the previewed pane. Redraws on Herdr events (herdr.Watcher) with a poll fallback. Also --dump (every level as text, no curses) and --split (map only, ~32 columns right of the caller).
# usage: python3 lib/map [--unit <workspace_id>] [--dump | --split]
# ---
# Ported from Horchestra's agentmap.py (https://github.com/SimoneDaniotti/horchestra),
# MIT License, Copyright (c) 2026 Simone Daniotti.
from __future__ import annotations

import argparse
import curses
import json
import locale
import os
import shlex
import sys
import threading
import time

LIB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if LIB not in sys.path:
    sys.path.insert(0, LIB)
import herdr  # noqa: E402

from . import activity, model, screen, views  # noqa: E402

POLL_SECONDS = 2.0
DEBOUNCE_SECONDS = 0.15
FRAME_SECONDS = 0.12  # edge animation step and input timeout
PREVIEW_SECONDS = 0.25
INTERACT_SECONDS = 0.1
HEADER_ROWS = 2
FOOTER_ROWS = 1
SIDE_BY_SIDE = 110  # columns from which the preview sits right of the map
MAP_MIN_WIDTH = 48
MAP_MIN_ROWS = 10
NOTICE_SECONDS = 6.0
SPLIT_WIDTH = 32
SPARK_WINDOW = 600
CTRL_RBRACKET = 29
SPECIAL_KEYS = {
    curses.KEY_UP: "up", curses.KEY_DOWN: "down", curses.KEY_LEFT: "left", curses.KEY_RIGHT: "right",
    curses.KEY_BACKSPACE: "backspace", curses.KEY_ENTER: "enter", curses.KEY_DC: "delete",
    curses.KEY_HOME: "home", curses.KEY_END: "end", curses.KEY_PPAGE: "pageup", curses.KEY_NPAGE: "pagedown",
    curses.KEY_BTAB: "shift+tab",
}
CONTROL_CHARS = {"\n": "enter", "\r": "enter", "\t": "tab", "\x1b": "esc", "\x7f": "backspace", "\x08": "backspace"}


def state_dir():
    return os.environ.get("PROMETHEUS_STATE_DIR") or os.path.expanduser("~/.local/state/prometheus")


def load_state():
    """dispatch.json, read-only and unlocked; {} when absent or mid-write."""
    try:
        with open(os.path.join(state_dir(), "dispatch.json")) as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def animation_enabled():
    return (os.environ.get("PROMETHEUS_MAP_ANIMATE") or "1").strip().lower() not in ("0", "off", "false", "no")


def help_lines():
    return [
        ("MAP", None),
        ("arrows  hjkl", "move between nodes"),
        ("Tab", "next node"),
        ("Enter, 2×click", "drill into a unit / the seat"),
        ("Esc  Bksp  u", "back up a level"),
        ("i, click preview", "interact with the previewed agent"),
        ("ctrl-]", "leave interact"),
        ("o", "open the agent's own tab"),
        ("p", "preview on / off"),
        ("r", "refresh"),
        ("q", "quit"),
        ("", None),
        ("MARKS", None),
        ("! / !N", "needs you / N below"),
        ("✉N", "held in dispatcher outbox"),
        ("?N", "proposals waiting"),
        ("╔═╗ ┏━┓ ╭─╮", "unit · seat · agent"),
    ]


def mark_view(pane_id, on):
    if not pane_id:
        return
    args = ["pane", "report-metadata", pane_id, "--source", herdr.SOURCE]
    args += ["--token", "view=map"] if on else ["--clear-token", "view"]
    try:
        herdr.call(*args)
    except herdr.HerdrError:
        pass


def wrap(text, width, lines):
    words, out, cur = text.split(), [], ""
    for word in words:
        if not cur:
            cur = word[:width]
        elif len(cur) + len(word) + 1 <= width:
            cur = f"{cur} {word}"
        else:
            out.append(cur)
            cur = word[:width]
        if len(out) == lines:
            break
    if cur and len(out) < lines:
        out.append(cur)
    return out


def runs(row):
    """[(column, text, attr)] for a parsed screen row; a wide character's empty second cell is skipped."""
    out = []
    for col, (ch, cell) in enumerate(row):
        if ch == "":
            continue
        if out and out[-1][2] == cell and out[-1][0] + out[-1][3] == col:
            out[-1][1] += ch
        else:
            out.append([col, ch, cell, 0])
        out[-1][3] += 2 if col + 1 < len(row) and row[col + 1][0] == "" else 1
    return [(c, t, a) for c, t, a, _ in out]


class PreviewReader(threading.Thread):
    """Reads the previewed pane off the UI thread, so a slow or hung `pane read` never stalls or kills the map."""

    def __init__(self):
        super().__init__(daemon=True)
        self.lock = threading.Lock()
        self.want = (None, 0, 0, PREVIEW_SECONDS)  # (pane, width, height, interval)
        self.result = {"key": None, "size": None, "rows": [], "clipped": False}
        self.changed = threading.Event()
        self.poke = threading.Event()

    def request(self, key, width, height, interval):
        with self.lock:
            changed = self.want[:3] != (key, width, height)
            self.want = (key, width, height, interval)
        if changed:
            self.poke.set()

    def latest(self):
        with self.lock:
            return dict(self.result)

    def run(self):
        while True:
            key, width, height, interval = self.want
            if key and width > 0 and height > 0:
                try:
                    rows, clipped = screen.parse(herdr.read_ansi(key), width, height)
                except Exception:  # noqa: BLE001 — a failed read keeps the last screen
                    rows = None
                if rows is not None:
                    with self.lock:
                        self.result = {"key": key, "size": (width, height), "rows": rows, "clipped": clipped}
                    self.changed.set()
            self.poke.wait(interval)
            self.poke.clear()


class App:
    def __init__(self, screen_, unit=None, preview=True):
        self.screen = screen_
        self.show_help = False
        self.own_pane = os.environ.get("HERDR_PANE_ID", "")
        self.tab_id = os.environ.get("HERDR_TAB_ID", "")
        self.tree = model.Tree()
        self.tabs = {}
        self.path = ["unit:" + unit] if unit else []
        self.selection = {}  # tuple(path) -> selected key
        self.hub, self.spokes = None, []
        self.boxes = {}
        self.preview_on = preview
        self.interact = None  # pane id keys go to
        self.typed = []
        self.reader = PreviewReader()
        self.preview_rect = None  # (y0, x0, y1, x1)
        self.pairs = {}
        self.scroll_y = 0
        self.hits = []  # [(y0, y1, x0, x1, key)] in screen coordinates
        self.error = ""
        self.last_refresh = 0.0
        self.last_click = (0.0, None)
        self.since = {}  # pane_id -> (status, monotonic time first seen)
        self.styles = {}
        self.watcher = herdr.Watcher()
        self.activity = activity.Activity()
        self.animate = animation_enabled()
        self.animating = False
        self.last_draw = 0.0
        self.notice = (0.0, "")

    # ---- data ---------------------------------------------------------------

    def refresh(self):
        self.last_refresh = time.monotonic()
        try:
            snap = herdr.snapshot()
        except herdr.HerdrError as exc:
            self.error = str(exc)[:120]
            return
        self.error = ""
        me = next((p for p in snap.get("panes") or [] if p.get("pane_id") == self.own_pane), None)
        if me:
            self.tab_id = me.get("tab_id") or self.tab_id
        self.tabs = {t.get("tab_id"): t.get("label") or "" for t in snap.get("tabs") or []}
        self.tree = model.build(snap, load_state(), own_pane=self.own_pane,
                                own_workspace=os.environ.get("HERDR_WORKSPACE_ID", ""), here_tab=self.tab_id)
        now = time.monotonic()
        for pane in self.tree.panes:
            key, status = pane.get("pane_id"), pane.get("agent_status")
            if self.since.get(key, (None,))[0] != status:
                self.since[key] = (status, now)
        self.watcher.watch(p["pane_id"] for p in self.tree.panes if p.get("agent"))
        try:
            self.activity.update(self.tree.panes)
        except (OSError, ValueError, TypeError):
            pass  # the sparkline is a nicety; never let it take the map down
        self.reader.poke.set()
        self.rebuild()

    def rebuild(self):
        hub, spokes = model.level(self.tree, self.path)
        while hub is None and self.path:
            self.path.pop()  # the unit closed under us
            hub, spokes = model.level(self.tree, self.path)
        self.hub, self.spokes = hub, spokes
        keys = [n.key for n in self.order()]
        sel = self.selection.get(tuple(self.path))
        if sel not in keys:
            sel = spokes[0].key if spokes else hub.key
        self.select(sel)
        if self.interact and self.interact not in self.tree.nodes:
            self.interact = None
            self.flash("agent closed; interact ended")

    def order(self):
        return ([self.hub] if self.hub else []) + self.spokes

    def node(self, key):
        return self.tree.nodes.get(key)

    def selected(self):
        return self.selection.get(tuple(self.path))

    def select(self, key):
        self.selection[tuple(self.path)] = key
        for n in self.order():
            n.selected = n.key == key

    def sparks(self, width):
        """Unit key -> a sparkline of its agents' activity over SPARK_WINDOW."""
        if self.path:
            return {}
        count = max(4, views.spoke_width(self.spokes, width) - 4)
        now = time.time()
        out = {}
        for key in self.tree.units:
            panes = [self.tree.pm.get(key)] + self.tree.workers[key]
            times = [t for p in panes if p for t in self.activity.times(p)]
            counts = activity.buckets(times, now, SPARK_WINDOW, count)
            out[key] = activity.sparkline(counts, max(counts + [1]))
        return out

    def flash(self, text):
        self.notice = (time.monotonic(), text)

    # ---- preview ------------------------------------------------------------

    def preview_key(self):
        if self.interact:
            return self.interact
        return model.preview_target(self.tree, self.selected())

    def preview_due(self):
        if self.reader.changed.is_set():
            self.reader.changed.clear()
            return bool(self.preview_on and self.preview_rect)
        return False

    # ---- drawing ------------------------------------------------------------

    def put(self, y, x, text, attr=0):
        h, w = self.screen.getmaxyx()
        if y < 0 or y >= h or x >= w or x < 0:
            return
        text = text[: max(0, w - x - (1 if y == h - 1 else 0))]
        try:
            self.screen.addstr(y, x, text, attr)
        except curses.error:
            pass

    def layout(self, h, w):
        """(map rect, preview rect or None) as (y0, x0, y1, x1), end-exclusive."""
        top, bottom = HEADER_ROWS, h - FOOTER_ROWS
        if not self.preview_on or self.show_help:
            return (top, 0, bottom, w), None
        if w >= SIDE_BY_SIDE:
            mw = max(MAP_MIN_WIDTH, int(w * 0.45))
            return (top, 0, bottom, mw), (top, mw, bottom, w)
        mh = max(MAP_MIN_ROWS, (bottom - top) // 2)
        if bottom - top - mh < 6:
            return (top, 0, bottom, w), None
        return (top, 0, top + mh, w), (top + mh, 0, bottom, w)

    def draw(self):
        self.screen.erase()
        h, w = self.screen.getmaxyx()
        attr = self.styles
        self.hits = []
        self.animating = False
        crumbs = ["PROMETHEUS"] + [("control" if p == model.CONTROL else self.node(p).name if self.node(p) else p)
                                   for p in self.path]
        self.put(0, 1, crumbs[0], curses.A_BOLD)
        x = 1 + len(crumbs[0])
        for c in crumbs[1:]:
            self.put(0, x, " › ", attr["dim"])
            self.put(0, x + 3, c, attr["accent"] | curses.A_BOLD)
            x += 3 + len(c)
        self.draw_stats(0, x + 2, w)
        self.put(1, 0, "─" * w, attr["dim"])

        map_rect, preview_rect = self.layout(h, w)
        self.preview_rect = preview_rect
        if self.show_help:
            self.draw_help(map_rect)
        elif self.error:
            self.put(map_rect[0], 1, "herdr unavailable, retrying…", attr["status:blocked"])
            self.put(map_rect[0] + 1, 1, self.error, attr["dim"])
        elif self.hub:
            self.draw_map(map_rect)
        if preview_rect:
            self.draw_preview(preview_rect)
        else:
            self.reader.request(None, 0, 0, POLL_SECONDS)
        self.draw_footer(h, w)
        self.last_draw = time.monotonic()
        self.screen.noutrefresh()
        curses.doupdate()

    def draw_stats(self, y, min_x, w):
        """Header stats, right-aligned; dropped from the left when they do not fit."""
        attr = self.styles
        t = self.tree
        n = sum(t.counts.values())
        parts = [(f"{views.STATUS[t.dispatcher][0]} dispatcher {t.dispatcher}", "status:" + t.dispatcher),
                 (f"{n} agent{'s' * (n != 1)}", "name")]
        for status in views.COUNT_ORDER:
            if t.counts.get(status):
                parts.append((f"{views.STATUS[status][0]}{t.counts[status]}", "status:" + status))
        if t.needs:
            parts.append((f"!{t.needs}", "needs"))
        if t.proposals:
            parts.append((f"?{len(t.proposals)}", "needs"))
        if t.held:
            parts.append((f"✉{t.held}", "accent"))
        while parts and sum(len(p) + 3 for p, _ in parts) - 3 > w - 1 - min_x:
            parts.pop()
        x = w - 1 - (sum(len(p) + 3 for p, _ in parts) - 3)
        for i, (text, style) in enumerate(parts):
            if i:
                self.put(y, x, " · ", attr["dim"])
                x += 3
            self.put(y, x, text, attr.get(style, 0))
            x += len(text)

    def draw_map(self, rect):
        y0, x0, y1, x1 = rect
        width, view_h = x1 - x0 - 1, y1 - y0
        canvas, boxes = views.render_level(self.hub, self.spokes, width, spark=self.sparks(width))
        self.boxes = boxes
        if self.animate:
            frame = int(time.monotonic() / FRAME_SECONDS)
            working = {n.key for n in self.spokes if n.status == "working"}
            self.animating = views.animate_edges(canvas, working, frame)
        box = boxes.get(self.selected())
        if box:
            if box[0] < self.scroll_y:
                self.scroll_y = box[0]
            elif box[1] >= self.scroll_y + view_h:
                self.scroll_y = box[1] - view_h + 1
        self.scroll_y = max(0, min(self.scroll_y, max(0, len(canvas.rows) - view_h)))
        for row in range(view_h):
            for x, text, style in canvas.runs(self.scroll_y + row):
                self.put(y0 + row, x0 + x, text, self.styles.get(style, 0))
        for key, (by0, by1, bx0, bx1) in boxes.items():
            self.hits.append((y0 + by0 - self.scroll_y, y0 + by1 - self.scroll_y, x0 + bx0, x0 + bx1, key))
        if not self.spokes:
            empty = "no units open" if not self.path else "no agents below"
            self.put(y0 + boxes[self.hub.key][1] + 2, x0 + 2, empty, self.styles["dim"])

    def preview_title(self, key):
        node = self.node(key)
        if not node:
            return ""
        raw = self.tree.raw.get(key) or {}
        t = model.tokens(raw)
        _, since = self.since.get(key, (node.status, time.monotonic()))
        bits = [node.name, f"{views.STATUS[node.status][1]} {model.ago(time.monotonic() - since)}"]
        tab = self.tabs.get(raw.get("tab_id"), "") or raw.get("tab_id", "")
        if tab:
            bits.append(f"tab {tab}")
        bits += [t[k] for k in ("item", "pr") if t.get(k)]
        if node.held:
            bits.append(f"✉{node.held}")
        return " · ".join(bits)

    def draw_preview(self, rect):
        y0, x0, y1, x1 = rect
        attr = self.styles
        border = attr["accent"] | curses.A_BOLD if self.interact else attr["dim"]
        w, h = x1 - x0, y1 - y0
        self.put(y0, x0, "┌" + "─" * (w - 2) + "┐", border)
        for y in range(y0 + 1, y1 - 1):
            self.put(y, x0, "│", border)
            self.put(y, x1 - 1, "│", border)
        self.put(y1 - 1, x0, "└" + "─" * (w - 2) + "┘", border)
        self.hits.append((y0, y1 - 1, x0, x1 - 1, "@preview"))
        inner_w, inner_h = w - 4, h - 2
        key = self.preview_key()
        if not key:
            self.reader.request(None, 0, 0, POLL_SECONDS)
            self.draw_preview_fallback(y0 + 1, x0 + 2, inner_w, inner_h)
            return
        title = f" {'INTERACT ' if self.interact else ''}{self.preview_title(key)} "
        self.put(y0, x0 + 2, views.fit(title, w - 4), border)
        self.reader.request(key, inner_w, inner_h, INTERACT_SECONDS if self.interact else PREVIEW_SECONDS)
        pv = self.reader.latest()
        if pv["key"] != key:
            self.put(y0 + 1, x0 + 2, "reading…", attr["dim"])
            return
        if pv["clipped"]:
            self.put(y1 - 1, x1 - 4, "»", attr["accent"])
        for i, row in enumerate(pv["rows"][:inner_h]):
            for col, text, cell in runs(row):
                self.put(y0 + 1 + i, x0 + 2 + col, text, self.cell_attr(cell))
        if not pv["rows"]:
            self.put(y0 + 1, x0 + 2, "no screen yet", attr["dim"])

    def draw_preview_fallback(self, y, x, w, h):
        attr = self.styles
        key = self.selected()
        node = self.node(key)
        raw = self.tree.raw.get(key) or {}
        if node and node.kind == "proposal":
            pid = raw.get("pid", "")
            lines = [("proposal · waiting on the operator", "accent"), (raw.get("reason") or "", None),
                     (raw.get("event") or "", "dim"), (f"proposal.sh approve {pid} | decline {pid}", "accent")]
        elif key in self.tree.units:
            lines = [("no PM in this unit yet", "dim"), (node.detail, None)]
        else:
            lines = [("nothing to preview", "dim")]
        row = y
        for text, style in lines:
            for part in wrap(text or "", w, 3):
                if row >= y + h:
                    return
                self.put(row, x, part, attr.get(style, 0) if style else 0)
                row += 1

    def cell_attr(self, cell):
        if cell is None:
            return 0
        a = 0
        if cell.bold:
            a |= curses.A_BOLD
        if cell.dim:
            a |= curses.A_DIM
        if cell.underline:
            a |= curses.A_UNDERLINE
        if cell.reverse:
            a |= curses.A_REVERSE
        if cell.italic:
            a |= getattr(curses, "A_ITALIC", 0)
        if cell.fg is None and cell.bg is None:
            return a
        return a | self.pair(self.color(cell.fg), self.color(cell.bg))

    def color(self, c):
        if c is None:
            return -1
        if isinstance(c, tuple):
            c = screen.nearest256(c)
        return c if c < curses.COLORS else c % 8

    def pair(self, fg, bg):
        key = (fg, bg)
        if key not in self.pairs:
            n = 16 + len(self.pairs)
            if n >= curses.COLOR_PAIRS:
                return 0
            try:
                curses.init_pair(n, fg, bg)
            except curses.error:
                return 0
            self.pairs[key] = n
        return curses.color_pair(self.pairs[key])

    def draw_help(self, rect):
        y0, x0, y1, _ = rect
        attr = self.styles
        row = y0
        for key, text in help_lines():
            if row >= y1:
                break
            if text is None:
                self.put(row, x0 + 1, key, attr["accent"] | curses.A_BOLD)
            else:
                self.put(row, x0 + 2, key, curses.A_BOLD)
                self.put(row, x0 + 20, text, attr["dim"])
            row += 1

    def draw_footer(self, h, w):
        attr = self.styles
        stamp, notice = self.notice
        if self.interact:
            node = self.node(self.interact)
            self.put(h - 1, 0, " " * (w - 1), attr["interact"])
            self.put(h - 1, 1, f"INTERACT {node.name if node else ''} — keys go to the agent · ctrl-] to leave",
                     attr["interact"])
        elif notice and time.monotonic() - stamp < NOTICE_SECONDS:
            self.put(h - 1, 1, notice, attr["status:blocked"])
        else:
            live = "live" if self.watcher.connected else "poll"
            back = "  esc back" if self.path else ""
            self.put(h - 1, 1, f"? keys  ⏎ drill{back}  i interact  o open  p preview  {live}", attr["dim"])

    # ---- navigation ---------------------------------------------------------

    def move(self, dy, dx):
        """Select the nearest box in a direction, by the boxes last drawn."""
        cur = self.boxes.get(self.selected())
        if not cur:
            return
        cy, cx = (cur[0] + cur[1]) / 2, (cur[2] + cur[3]) / 2
        best = None
        for key, (y0, y1, x0, x1) in self.boxes.items():
            if key == self.selected():
                continue
            ny, nx = (y0 + y1) / 2, (x0 + x1) / 2
            along = (ny - cy) * dy + (nx - cx) * dx
            if along <= 0:
                continue
            across = abs((nx - cx) * dy) + abs((ny - cy) * dx)
            score = along + across * 3
            if best is None or score < best[0]:
                best = (score, key)
        if best:
            self.select(best[1])

    def cycle(self):
        keys = [n.key for n in self.order()]
        if keys:
            i = keys.index(self.selected()) if self.selected() in keys else -1
            self.select(keys[(i + 1) % len(keys)])

    def drill(self, key=None):
        key = key or self.selected()
        nxt = model.drill_path(self.tree, key)
        if nxt is None:
            if self.path:
                self.flash("no level below an agent · i to interact, o to open its tab")
            return
        if nxt in self.path:
            return
        self.path.append(nxt)
        self.scroll_y = 0
        self.rebuild()

    def up(self):
        if self.path:
            came_from = self.path.pop()
            self.scroll_y = 0
            if came_from == model.CONTROL and self.tree.seat:
                came_from = self.tree.seat
            self.selection[tuple(self.path)] = came_from
            self.rebuild()

    def start_interact(self):
        key = self.preview_key()
        if not key or not self.preview_on:
            self.flash("nothing to interact with here")
            return
        self.interact = key
        self.reader.poke.set()

    def open_pane(self):
        key = self.selected()
        raw = self.tree.raw.get(key) or {}
        target = model.preview_target(self.tree, key)
        try:
            if target:
                try:
                    herdr.call("agent", "focus", target)
                except herdr.HerdrError:
                    praw = self.tree.raw.get(target) or {}
                    herdr.call("workspace", "focus", praw["workspace_id"])
                    herdr.call("tab", "focus", praw["tab_id"])
            elif raw.get("workspace_id"):
                herdr.call("workspace", "focus", raw["workspace_id"])
            else:
                self.flash("nothing to open")
        except (herdr.HerdrError, KeyError) as exc:
            self.flash(f"could not open: {exc}"[:80])

    # ---- input --------------------------------------------------------------

    def on_mouse(self):
        try:
            _, mx, my, _, bstate = curses.getmouse()
        except curses.error:
            return
        if bstate & getattr(curses, "BUTTON4_PRESSED", 0):
            self.scroll_y = max(0, self.scroll_y - 2)
            return
        if bstate & getattr(curses, "BUTTON5_PRESSED", 0):
            self.scroll_y += 2
            return
        if not bstate & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED):
            return
        key = next((k for y0, y1, x0, x1, k in self.hits if y0 <= my <= y1 and x0 <= mx <= x1), None)
        if key == "@preview":
            if not self.interact:
                self.start_interact()
            return
        if key is None:
            return
        self.interact = None
        now = time.monotonic()
        repeat = self.last_click[1] == key and now - self.last_click[0] < 0.4
        self.select(key)
        self.last_click = (now, key)
        if bstate & curses.BUTTON1_DOUBLE_CLICKED or repeat:
            self.drill(key)

    def handle(self, ch):
        """One key from get_wch (str or int) in map mode; False quits."""
        if ch == curses.KEY_MOUSE:
            self.on_mouse()
            return True
        if ch == curses.KEY_RESIZE:
            self.sync_size()
            return True
        if self.show_help:
            self.show_help = False
            return True
        if ch == "?":
            self.show_help = True
        elif ch == "q":
            return False
        elif ch in (curses.KEY_UP, "k", "w"):
            self.move(-1, 0)
        elif ch in (curses.KEY_DOWN, "j", "s"):
            self.move(1, 0)
        elif ch in (curses.KEY_LEFT, "h", "a"):
            self.move(0, -1)
        elif ch in (curses.KEY_RIGHT, "l", "d"):
            self.move(0, 1)
        elif ch == "\t":
            self.cycle()
        elif ch in (curses.KEY_ENTER, "\n", "\r"):
            self.drill()
        elif ch in ("\x1b", curses.KEY_BACKSPACE, "\x7f", "\x08", "u"):
            self.up()
        elif ch == "i":
            self.start_interact()
        elif ch == "o":
            self.open_pane()
        elif ch == "p":
            self.preview_on = not self.preview_on
            self.interact = None
        elif ch == "r":
            self.refresh()
        return True

    def forward(self, ch):
        """One key in interact mode: printable text is buffered, everything else flushes and is sent."""
        if ch == curses.KEY_MOUSE:
            self.flush_typed()
            self.on_mouse()
            return
        if ch == curses.KEY_RESIZE:
            self.sync_size()
            return
        if ch == chr(CTRL_RBRACKET):
            self.flush_typed()
            self.interact = None
            return
        if isinstance(ch, str) and ch >= " " and ch != "\x7f":
            self.typed.append(ch)
            return
        name = SPECIAL_KEYS.get(ch) if isinstance(ch, int) else CONTROL_CHARS.get(ch)
        if name is None and isinstance(ch, str) and "\x01" <= ch <= "\x1a":
            name = "ctrl+" + chr(ord(ch) + 96)
        if name is None:
            return
        self.flush_typed()
        self.send("send-keys", name)

    def flush_typed(self):
        if self.typed:
            text, self.typed = "".join(self.typed), []
            self.send("send-text", text)

    def send(self, verb, arg):
        try:
            herdr.call("pane", verb, self.interact, arg, timeout=5)
        except herdr.HerdrError as exc:
            self.flash(f"send failed: {exc}"[:80])
        self.reader.poke.set()

    # ---- loop ---------------------------------------------------------------

    def sync_size(self):
        """Follow pane resizes even if SIGWINCH never reaches curses."""
        try:
            size = os.get_terminal_size(sys.__stdout__.fileno())
        except OSError:
            return False
        if (size.lines, size.columns) == self.screen.getmaxyx():
            return False
        curses.resizeterm(size.lines, size.columns)
        return True

    def getkey(self):
        try:
            return self.screen.get_wch()
        except curses.error:
            return None

    def run(self):
        self.watcher.start()
        self.reader.start()
        self.refresh()
        self.draw()
        while True:
            ch = self.getkey()
            if ch is not None:
                if self.interact:
                    self.forward(ch)
                elif not self.handle(ch):
                    return
                if not self.typed:
                    self.draw()
                continue
            self.flush_typed()
            redraw = self.sync_size() or self.preview_due()
            if self.animating and time.monotonic() - self.last_draw >= FRAME_SECONDS:
                redraw = True
            if self.watcher.changed.is_set():
                time.sleep(DEBOUNCE_SECONDS)
                self.watcher.changed.clear()
                self.refresh()
                redraw = True
            elif time.monotonic() - self.last_refresh >= POLL_SECONDS:
                self.refresh()
                redraw = True
            if redraw:
                self.draw()


def make_styles():
    """Map views.py style names to curses attributes."""
    rich = curses.COLORS >= 256
    palette = {
        1: curses.COLOR_YELLOW,   # working
        2: curses.COLOR_RED,      # blocked / needs you
        3: curses.COLOR_GREEN,    # done / running
        4: -1,                    # idle / default
        5: curses.COLOR_CYAN,     # this tab, accent
        6: 208 if rich else curses.COLOR_RED,  # claude orange
    }
    for pair, color in palette.items():
        curses.init_pair(pair, color, -1)
    curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_CYAN)
    cp, bold, dim = curses.color_pair, curses.A_BOLD, curses.A_DIM
    return {
        None: 0,
        "dim": dim,
        "name": bold,
        "selname": bold | curses.A_REVERSE,
        "rail": dim,
        "border": dim,
        "here": cp(5),
        "sel": cp(5) | bold,
        "sel_here": cp(5) | bold,
        "accent": cp(5),
        "spark": cp(5),
        "interact": cp(7) | bold,
        "needs": cp(2) | bold,
        "status:working": cp(1) | bold,
        "status:blocked": cp(2) | bold,
        "status:done": cp(3) | bold,
        "status:running": cp(3) | bold,
        "status:stopped": cp(2),
        "status:waiting": cp(2) | bold,
        "status:idle": dim,
        "status:unknown": dim,
        "flow": cp(1),
        "pulse": cp(1) | bold,
        "kind:claude": cp(6) | bold,
        "kind:other": bold,
    }


def setup(screen_, unit=None, preview=True):
    curses.curs_set(0)
    curses.use_default_colors()
    curses.mousemask(curses.ALL_MOUSE_EVENTS)
    curses.mouseinterval(0)
    screen_.timeout(int(FRAME_SECONDS * 1000))
    screen_.keypad(True)
    app = App(screen_, unit=unit, preview=preview)
    app.styles = make_styles()
    app.run()


# ---- entry points ----------------------------------------------------------


def dump():
    tree = model.build(herdr.snapshot(), load_state(), own_pane=os.environ.get("HERDR_PANE_ID", ""),
                       own_workspace=os.environ.get("HERDR_WORKSPACE_ID", ""))
    print(model.to_text(tree))
    return 0


def _rects(pane_id):
    layout = herdr.call("pane", "layout", "--pane", pane_id).get("layout") or {}
    return {p.get("pane_id"): p.get("rect") or {} for p in layout.get("panes") or []}


def split(unit=None):
    """Open the map (preview off) in a new pane right of the caller, ~SPLIT_WIDTH columns wide."""
    caller = os.environ.get("HERDR_PANE_ID")
    if not caller:
        print("map: --split needs HERDR_PANE_ID (run inside Herdr)", file=sys.stderr)
        return 2
    size = int(os.environ.get("PROMETHEUS_MAP_WIDTH") or SPLIT_WIDTH)
    width = _rects(caller).get(caller, {}).get("width") or 0
    args = ["pane", "split", caller, "--direction", "right", "--cwd", os.getcwd(), "--no-focus"]
    if width > size * 2:
        args += ["--ratio", "%.4f" % (1 - size / width)]
    new = (herdr.call(*args).get("pane") or {}).get("pane_id")
    if not new:
        print("map: pane split returned no pane id", file=sys.stderr)
        return 1
    cmd = [sys.executable, os.path.dirname(os.path.abspath(__file__)), "--no-preview"]
    cmd += ["--unit", unit] if unit else []
    herdr.call("pane", "run", new, " ".join(shlex.quote(c) for c in cmd))
    for _ in range(3):  # nudge the divider until the map is `size` wide (Horchestra toggle.fit)
        boxes = _rects(new)
        mine, other = boxes.get(new), boxes.get(caller)
        if not mine or not other:
            break
        total = mine.get("width", 0) + other.get("width", 0)
        excess = mine.get("width", 0) - size
        if total <= 0 or abs(excess) <= 1:
            break
        try:
            herdr.call("pane", "resize", "--direction", "right" if excess > 0 else "left",
                       "--amount", "%.4f" % (abs(excess) / total), "--pane", new)
        except herdr.HerdrError:
            break
    print(new)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="map", description="prometheus agent map")
    ap.add_argument("--unit", help="open at one unit workspace id's level")
    ap.add_argument("--dump", action="store_true", help="print every level as text, no curses")
    ap.add_argument("--split", action="store_true", help="open the map (no preview) in a new pane right of this one")
    ap.add_argument("--no-preview", action="store_true", help="start with the preview off")
    a = ap.parse_args(argv)
    try:
        if a.dump:
            return dump()
        if a.split:
            return split(a.unit)
    except herdr.HerdrError as exc:
        print(f"map: {exc}", file=sys.stderr)
        return 1
    locale.setlocale(locale.LC_ALL, "")
    os.environ.setdefault("ESCDELAY", "25")
    # Inherited LINES/COLUMNS would pin curses to the launch size; always ask the terminal.
    os.environ.pop("LINES", None)
    os.environ.pop("COLUMNS", None)
    curses.use_env(False)
    own = os.environ.get("HERDR_PANE_ID", "")
    mark_view(own, True)
    try:
        curses.wrapper(setup, a.unit, not a.no_preview)
    except KeyboardInterrupt:
        pass
    finally:
        mark_view(own, False)
    return 0
