# ---
# name: map.app
# description: The prometheus map's curses front end — header counts, cards / graph / compact views with live working edges, details box, activity plot, key + mouse input, Enter to focus an agent / unit; redraws on Herdr events (herdr.Watcher) with a 2s poll fallback. Also --dump (tree as text, no curses) and --split (open the map in a ~32-column pane right of the caller).
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
import re
import shlex
import sys
import time

LIB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if LIB not in sys.path:
    sys.path.insert(0, LIB)
import herdr  # noqa: E402

from . import activity, model, views  # noqa: E402

POLL_SECONDS = 2.0
DEBOUNCE_SECONDS = 0.15
HEADER_ROWS = 4
FOOTER_ROWS = 2
DETAILS_ROWS = 8
GRAPH_MIN_WIDTH = 60
MODES = ["auto", "cards", "graph", "compact"]
FRAME_SECONDS = 0.12  # edge animation step
MAP_MIN_ROWS = 8  # the activity plot never squeezes the map below this
MIN_LANES = 2
NOTICE_SECONDS = 6.0
SPLIT_WIDTH = 32


# ---- data -----------------------------------------------------------------


def state_dir():
    return os.environ.get("PROMETHEUS_STATE_DIR") or os.path.expanduser("~/.claude/prometheus")


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
        ("KEYS IN THIS MAP", None),
        ("w s  ↑ ↓  k j", "move selection"),
        ("a d  ← →  h l", "parent / child"),
        ("g G  Home End", "first / last"),
        ("Enter, 2×click", "focus agent's pane / unit's space"),
        ("click, wheel", "select / move"),
        ("Space", "fold / unfold"),
        ("v", "cycle views: auto cards graph compact"),
        ("i", "details box"),
        ("t", "activity plot"),
        ("[ ]", "activity: shorter / longer"),
        ("r", "refresh"),
        ("q", "close this map"),
        ("?", "show / hide help"),
        ("", None),
        ("MARKS", None),
        ("! / !N", "needs you / N below"),
        ("✉N", "N held in dispatcher outbox"),
        ("▌", "in this map's tab"),
    ]


CHROME = re.compile(r"^(❯|>|⏵|\?|esc|ctrl|shift|tab to|↑|↓|─|━|═|\$|%)", re.I)
SHELL_PROMPT = re.compile(r"^\S+@\S+.*[%$#]\s*$")


def last_message(text):
    """Best-effort last thing the agent said, from its recent screen."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in reversed(lines):
        if line[:1] in ("⏺", "•", "●") and len(line) > 2:
            return line[1:].strip()
    for line in reversed(lines):
        letters = sum(ch.isalnum() for ch in line)
        if letters >= 8 and letters / max(1, len(line)) > 0.5 and not CHROME.match(line) \
                and not SHELL_PROMPT.match(line) and "tokens" not in line.lower():
            return line
    return ""


def wrap(text, width, lines):
    words, out, cur = text.split(), [], ""
    for word in words:
        if not cur:
            cur = word if len(word) <= width else word[: max(1, width - 1)] + "…"
        elif len(cur) + len(word) + 1 <= width:
            cur = f"{cur} {word}"
        else:
            out.append(cur)
            cur = word[:width]
        if len(out) == lines:
            break
    if cur and len(out) < lines:
        out.append(cur)
    if len(out) == lines and len(" ".join(out)) < len(text):
        out[-1] = out[-1][: max(0, width - 1)] + "…"
    return out


def mark_view(pane_id, on):
    if not pane_id:
        return
    args = ["pane", "report-metadata", pane_id, "--source", herdr.SOURCE]
    args += ["--token", "view=map"] if on else ["--clear-token", "view"]
    try:
        herdr.call(*args)
    except herdr.HerdrError:
        pass


# ---- app --------------------------------------------------------------------


class App:
    def __init__(self, screen, unit=None):
        self.screen = screen
        self.unit = unit
        self.show_help = False
        self.own_pane = os.environ.get("HERDR_PANE_ID", "")
        self.tab_id = os.environ.get("HERDR_TAB_ID", "")
        self.label = ""
        self.tree = model.Tree()
        self.tabs = {}
        self.order = []
        self.selected = None
        self.collapsed = set()
        self.mode = "auto"
        self.show_details = True
        self.scroll_y = 0
        self.scroll_x = 0
        self.hits = []  # [(y0, y1, x0, x1, key)] in screen coordinates
        self.error = ""
        self.last_refresh = 0.0
        self.last_click = (0.0, None)
        self.since = {}  # pane_id -> (status, monotonic time first seen)
        self.messages = {}  # pane_id -> (monotonic time, text)
        self.styles = {}
        self.watcher = herdr.Watcher()
        self.activity = activity.Activity()
        self.show_activity = True
        self.window = 1  # index into activity.WINDOWS
        self.animate = animation_enabled()
        self.animating = False
        self.last_draw = 0.0
        self.notice = (0.0, "")
        self._lanes_cache = (None, [])

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
        self.tree = model.build(snap, load_state(), own_pane=self.own_pane, unit=self.unit,
                                here_tab=self.tab_id)
        if self.unit:
            ws = next((w for w in snap.get("workspaces") or [] if w.get("workspace_id") == self.unit), {})
            self.label = model.tokens(ws).get("unit") or ws.get("label") or self.unit
        else:
            self.label = f"dispatcher {self.tree.dispatcher}"
        now = time.monotonic()
        for pane in self.tree.panes:
            key, status = pane.get("pane_id"), pane.get("agent_status")
            if self.since.get(key, (None,))[0] != status:
                self.since[key] = (status, now)
        self.watcher.watch(p["pane_id"] for p in self.tree.panes if p.get("agent"))
        try:
            self.activity.update(self.tree.panes)
        except (OSError, ValueError, TypeError):
            pass  # the plot is a nicety; never let it take the map down
        self.messages.pop(self.selected, None)
        self.rebuild()

    def rebuild(self):
        for key, node in self.tree.nodes.items():
            node.collapsed = key in self.collapsed
            node.selected = key == self.selected
        self.order = model.visible_order(self.tree.roots)
        keys = [n.key for n in self.order]
        if self.selected not in keys:
            here = [n.key for n in self.order if n.here]
            self.select((here or keys or [None])[0])

    def node(self, key):
        return next((n for n in self.order if n.key == key), None)

    def is_agent(self, key):
        return bool(key) and key in {p["pane_id"] for p in self.tree.panes}

    def message_for(self, key):
        cached = self.messages.get(key)
        if cached and time.monotonic() - cached[0] < POLL_SECONDS:
            return cached[1]
        try:
            text = last_message(herdr.read(key))
        except Exception:
            text = ""
        self.messages[key] = (time.monotonic(), text)
        return text

    def lanes(self, width):
        """[(node, counts or None)] for the activity plot: one lane per agent."""
        window = activity.WINDOWS[self.window]
        now = time.time()
        stamp = (window, width, int(now), id(self.tree), self.selected)
        if self._lanes_cache[0] == stamp:
            return self._lanes_cache[1]
        nodes = [n for n in self.order if self.is_agent(n.key)]
        count = views.activity_spark_width([(n, None) for n in nodes], width) or 1
        out = []
        for node in nodes:
            if not self.activity.has_history(node.key):
                out.append((node, None))
                continue
            out.append((node, activity.buckets(self.activity.times(node.key), now, window, count)))
        self._lanes_cache = (stamp, out)
        return out

    def flash(self, text):
        self.notice = (time.monotonic(), text)

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

    def effective_mode(self, width):
        if self.mode != "auto":
            return self.mode
        if width >= GRAPH_MIN_WIDTH and views.graph_width(self.tree.roots) <= width:
            return "graph"
        return "cards"

    def draw(self):
        self.screen.erase()
        h, w = self.screen.getmaxyx()
        attr = self.styles
        mode = self.effective_mode(w)

        self.put(0, 1, "PROMETHEUS", curses.A_BOLD)
        tag = f"[{mode}]" if self.mode == "auto" else f"[{mode}*]"
        self.put(0, w - len(tag) - 1, tag, attr["dim"])
        self.put(1, 1, self.label, attr["accent"] | curses.A_BOLD)
        x = 1
        agents = [n for n in self.order if self.is_agent(n.key)]
        counts = {}
        for node in agents:
            counts[node.status] = counts.get(node.status, 0) + 1
        needs = sum(1 for n in agents if n.needs)
        badges = [(f"?{len(self.tree.proposals)}", "needs", self.tree.proposals),
                  (f"!{needs}", "needs", needs), (f"✉{self.tree.held}", "accent", self.tree.held)]
        for text, style, shown in badges:
            if shown:
                self.put(2, x, text, attr[style])
                x += len(text) + 1
        for status in ("blocked", "working", "done", "idle"):
            if counts.get(status):
                text = f"{views.STATUS[status][0]}{counts[status]}"
                self.put(2, x, text, attr["status:" + status])
                x += len(text) + 1
        self.put(3, 0, "─" * w, attr["dim"])

        details = DETAILS_ROWS if self.show_details and h >= HEADER_ROWS + FOOTER_ROWS + DETAILS_ROWS + 8 else 0
        footer = FOOTER_ROWS if h > 12 else 0
        lanes, plot = [], 0
        if self.show_activity and self.order and not self.show_help and not self.error:
            lanes = self.lanes(w)
            spare = h - HEADER_ROWS - footer - details - MAP_MIN_ROWS - 3
            if lanes and spare >= min(MIN_LANES, len(lanes)):
                lanes = self._lane_window(lanes, spare)
                plot = len(lanes) + 3
            else:
                lanes = []
        top, bottom = HEADER_ROWS, h - footer - details - plot
        view_h = max(0, bottom - top)
        self.hits = []
        self.animating = False

        if self.show_help:
            details = 0
            self.draw_help(top, h - footer, w)
        elif self.error:
            self.put(top, 1, "herdr unavailable, retrying…", attr["status:blocked"])
            self.put(top + 1, 1, self.error, attr["dim"])
        elif not self.order:
            self.put(top, 1, f"no unit {self.unit}" if self.unit else "nothing to show", attr["dim"])
        else:
            renderer = {"cards": views.render_cards, "graph": views.render_graph,
                        "compact": views.render_compact}[mode]
            canvas, boxes = renderer(self.tree.roots, w)
            if self.animate:
                frame = int(time.monotonic() / FRAME_SECONDS)
                working = {n.key for n in self.order if n.status == "working" and self.is_agent(n.key)}
                self.animating = views.animate_edges(canvas, working, frame)
            self.blit(canvas, boxes, top, view_h, w)

        if plot:
            self.draw_activity(lanes, bottom, w)
        if details and not self.show_help:
            self.draw_details(h - footer - details, details, w)
        if footer:
            self.put(h - 2, 0, "─" * w, attr["dim"])
            stamp, notice = self.notice
            if notice and time.monotonic() - stamp < NOTICE_SECONDS:
                self.put(h - 1, 1, notice, attr["status:blocked"])
            else:
                live = "live" if self.watcher.connected else "poll"
                self.put(h - 1, 1, f"? keys  v view  ⏎ focus  {live}", attr["dim"])
        self.last_draw = time.monotonic()
        self.screen.noutrefresh()
        curses.doupdate()

    def blit(self, canvas, boxes, top, view_h, w):
        """Draw the canvas, scrolled so the selected node is visible."""
        box = boxes.get(self.selected)
        if box:
            y0, y1, x0, x1 = box
            if y0 < self.scroll_y:
                self.scroll_y = y0
            elif y1 >= self.scroll_y + view_h:
                self.scroll_y = y1 - view_h + 1
            if x0 < self.scroll_x:
                self.scroll_x = x0
            elif x1 >= self.scroll_x + w:
                self.scroll_x = x1 - w + 1
        self.scroll_y = max(0, min(self.scroll_y, max(0, len(canvas.rows) - view_h)))
        self.scroll_x = max(0, min(self.scroll_x, max(0, canvas.width - w)))
        for row in range(view_h):
            cy = self.scroll_y + row
            for x, text, style in canvas.runs(cy, self.scroll_x, self.scroll_x + w):
                self.put(top + row, x - self.scroll_x, text, self.styles.get(style, 0))
        for key, (y0, y1, x0, x1) in boxes.items():
            self.hits.append((top + y0 - self.scroll_y, top + y1 - self.scroll_y,
                              x0 - self.scroll_x, x1 - self.scroll_x, key))

    def _lane_window(self, lanes, rows):
        """At most `rows` lanes, keeping the selected one in view."""
        if len(lanes) <= rows:
            return lanes
        keys = [n.key for n, _ in lanes]
        i = keys.index(self.selected) if self.selected in keys else 0
        start = max(0, min(i - rows // 2, len(lanes) - rows))
        return lanes[start:start + rows]

    def draw_activity(self, lanes, y, w):
        self.put(y, 0, "─" * w, self.styles["dim"])
        canvas, boxes = views.render_activity(
            lanes, w, activity.window_label(activity.WINDOWS[self.window]), activity.sparkline)
        for row in range(len(canvas.rows)):
            for x, text, style in canvas.runs(row):
                self.put(y + 1 + row, x, text, self.styles.get(style, 0))
        for key, (y0, y1, x0, x1) in boxes.items():
            self.hits.append((y + 1 + y0, y + 1 + y1, x0, x1, key))

    def draw_help(self, top, bottom, w):
        """Key list; descriptions that do not fit beside a key wrap below it."""
        attr = self.styles
        lines = help_lines()
        key_w = max(len(k) for k, t in lines if t) + 2
        desc_x = 2 + key_w
        row = top
        for key, text in lines:
            if row >= bottom:
                break
            if text is None:
                self.put(row, 1, key, attr["accent"] | curses.A_BOLD)
                row += 1
                continue
            self.put(row, 2, key, curses.A_BOLD)
            if len(text) <= w - desc_x - 1:
                self.put(row, desc_x, text, attr["dim"])
                row += 1
                continue
            row += 1
            for part in wrap(text, max(8, w - 7), 2):
                if row >= bottom:
                    break
                self.put(row, 6, part, attr["dim"])
                row += 1

    def fields_for(self, node):
        """(subtitle, [(label, text, style)]) for the details box."""
        raw = self.tree.raw.get(node.key) or {}
        t = model.tokens(raw)
        if self.is_agent(node.key):
            status, since = self.since.get(node.key, (node.status, time.monotonic()))
            tab = self.tabs.get(raw.get("tab_id"), "") or raw.get("tab_id", "")
            sub = f"{t.get('role') or raw.get('agent') or 'pane'} · {views.STATUS[node.status][1]} " \
                  f"{model.ago(time.monotonic() - since)} · tab {tab}"
            fields = []
            if node.needs:
                fields.append(("needs", t.get("status") or "needs you", "needs"))
            elif t.get("status"):
                fields.append(("status", t["status"], "name"))
            for k in ("item", "pr", "worktree"):
                if t.get(k):
                    fields.append((k, t[k], None))
            held = (load_state().get("outbox") or {}).get(node.key) or []
            if held:
                fields.append(("held", f"{len(held)}: " + " | ".join(str(i.get("line", "")) for i in held[-3:]),
                               "accent"))
            message = self.message_for(node.key)
            if message:
                fields.append(("last", message, None))
            return sub, fields
        if node.kind == "unit":
            sub = " · ".join(v for v in (t.get("kind"), t.get("project"), t.get("stage")) if v)
            fields = [(k, ", ".join(model.csv(t.get(k))), None) for k in ("stories", "prs") if t.get(k)]
            if node.detail:
                fields.append(("change", node.detail.rsplit(" · ", 1)[-1], "dim"))
            return sub + " · Enter to open", fields
        if node.kind == "proposal":
            pid = raw.get("pid", "")
            return "proposal · waiting on the operator", [
                ("why", raw.get("reason") or "", None),
                ("event", raw.get("event") or "", "dim"),
                ("answer", f"proposal.sh approve {pid} | decline {pid}", "accent"),
            ]
        if node.kind == "dispatcher":
            return f"{self.tree.dispatcher} · state {state_dir()}", [("queue", node.detail, None)]
        return node.detail, []

    def draw_details(self, y, rows, w):
        attr = self.styles
        node = self.node(self.selected)
        self.put(y, 0, "─" * w, attr["dim"])
        self.put(y, 2, f" {node.name} " if node else " ", attr["accent"] | curses.A_BOLD)
        if not node:
            return
        sub, fields = self.fields_for(node)
        self.put(y + 1, 1, sub[: w - 2], attr["dim"])
        row = y + 2
        label_w = 7
        for label, text, style in fields:
            budget = y + rows - row
            if budget <= 0 or not text:
                continue
            chunk = wrap(text, max(8, w - label_w - 2), min(2, budget))
            self.put(row, 1, label[:label_w - 1], attr["dim"])
            for i, part in enumerate(chunk):
                self.put(row + i, label_w + 1, part, attr.get(style, 0) if style else 0)
            row += len(chunk)

    # ---- input --------------------------------------------------------------

    def select(self, key):
        self.selected = key
        for node in self.order:
            node.selected = node.key == key

    def move(self, delta):
        keys = [n.key for n in self.order]
        if keys:
            i = keys.index(self.selected) if self.selected in keys else 0
            self.select(keys[max(0, min(len(keys) - 1, i + delta))])

    def toggle_fold(self):
        node = self.node(self.selected)
        if node and node.children:
            self.collapsed ^= {node.key}
            self.rebuild()

    def to_parent(self):
        node = self.node(self.selected)
        if node and node.parent:
            self.select(node.parent.key)

    def to_child(self):
        node = self.node(self.selected)
        if node and node.collapsed:
            self.toggle_fold()
        elif node and node.children:
            self.select(node.children[0].key)

    def activate(self):
        node = self.node(self.selected)
        if not node:
            return
        raw = self.tree.raw.get(node.key) or {}
        if node.kind == "proposal":
            self.flash(f"answer: proposal.sh approve|decline {raw.get('pid', '')}")
            return
        try:
            if self.is_agent(node.key):
                try:
                    herdr.call("agent", "focus", node.key)
                except herdr.HerdrError:
                    herdr.call("workspace", "focus", raw["workspace_id"])
                    herdr.call("tab", "focus", raw["tab_id"])
            elif raw.get("workspace_id"):
                herdr.call("workspace", "focus", raw["workspace_id"])
            else:
                self.flash("nothing to focus")
        except (herdr.HerdrError, KeyError) as exc:
            self.flash(f"could not focus: {exc}"[:80])

    def on_mouse(self):
        try:
            _, mx, my, _, bstate = curses.getmouse()
        except curses.error:
            return
        if bstate & getattr(curses, "BUTTON4_PRESSED", 0):
            self.move(-1)
            return
        if bstate & getattr(curses, "BUTTON5_PRESSED", 0):
            self.move(1)
            return
        if not bstate & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED):
            return
        key = next((k for y0, y1, x0, x1, k in self.hits if y0 <= my <= y1 and x0 <= mx <= x1), None)
        if key is None:
            return
        now = time.monotonic()
        repeat = self.last_click[1] == key and now - self.last_click[0] < 0.4
        self.select(key)
        self.last_click = (now, key)
        if bstate & curses.BUTTON1_DOUBLE_CLICKED or repeat:
            self.activate()

    def handle(self, key):
        if self.show_help and key in (ord("?"), ord("q"), 27):
            self.show_help = False
            return True
        if key == ord("?"):
            self.show_help = True
            return True
        if key == ord("q"):
            return False
        if key in (curses.KEY_UP, ord("w"), ord("k")):
            self.move(-1)
        elif key in (curses.KEY_DOWN, ord("s"), ord("j")):
            self.move(1)
        elif key in (curses.KEY_LEFT, ord("a"), ord("h")):
            self.to_parent()
        elif key in (curses.KEY_RIGHT, ord("d"), ord("l")):
            self.to_child()
        elif key in (curses.KEY_HOME, ord("g")):
            self.move(-len(self.order))
        elif key in (curses.KEY_END, ord("G")):
            self.move(len(self.order))
        elif key in (curses.KEY_ENTER, 10, 13):
            self.activate()
        elif key == ord(" "):
            self.toggle_fold()
        elif key == ord("v"):
            self.mode = MODES[(MODES.index(self.mode) + 1) % len(MODES)]
            self.scroll_x = self.scroll_y = 0
        elif key == ord("i"):
            self.show_details = not self.show_details
        elif key == ord("t"):
            self.show_activity = not self.show_activity
        elif key == ord("["):
            self.window = max(0, self.window - 1)
        elif key == ord("]"):
            self.window = min(len(activity.WINDOWS) - 1, self.window + 1)
        elif key == ord("r"):
            self.refresh()
        elif key == curses.KEY_MOUSE:
            self.on_mouse()
        elif key == curses.KEY_RESIZE:
            self.sync_size()
        return True

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

    def run(self):
        self.watcher.start()
        self.refresh()
        self.draw()
        while True:
            key = self.screen.getch()
            if key != -1:
                if not self.handle(key):
                    return
                self.draw()
                continue
            if self.sync_size():
                self.draw()
            if self.animating and time.monotonic() - self.last_draw >= FRAME_SECONDS:
                self.draw()
            if self.watcher.changed.is_set():
                time.sleep(DEBOUNCE_SECONDS)
                self.watcher.changed.clear()
                self.refresh()
                self.draw()
            elif time.monotonic() - self.last_refresh >= POLL_SECONDS:
                self.refresh()
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
    cp, bold, dim = curses.color_pair, curses.A_BOLD, curses.A_DIM
    return {
        None: 0,
        "dim": dim,
        "name": bold,
        "selname": bold | curses.A_REVERSE,
        "selrow": curses.A_REVERSE,
        "rail": dim,
        "border": dim,
        "here": cp(5),
        "sel": bold,
        "sel_here": cp(5) | bold,
        "accent": cp(5),
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


def setup(screen, unit=None):
    curses.curs_set(0)
    curses.use_default_colors()
    curses.mousemask(curses.ALL_MOUSE_EVENTS)
    curses.mouseinterval(0)
    screen.timeout(int(FRAME_SECONDS * 1000))
    screen.keypad(True)
    app = App(screen, unit=unit)
    app.styles = make_styles()
    app.run()


# ---- entry points ----------------------------------------------------------


def dump(unit=None):
    tree = model.build(herdr.snapshot(), load_state(), own_pane=os.environ.get("HERDR_PANE_ID", ""), unit=unit)
    print(model.to_text(tree.roots) or "(empty)")
    return 0


def _rects(pane_id):
    layout = herdr.call("pane", "layout", "--pane", pane_id).get("layout") or {}
    return {p.get("pane_id"): p.get("rect") or {} for p in layout.get("panes") or []}


def split(unit=None):
    """Open the map in a new pane right of the caller, ~SPLIT_WIDTH columns wide."""
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
    cmd = [sys.executable, os.path.dirname(os.path.abspath(__file__))] + (["--unit", unit] if unit else [])
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
    ap.add_argument("--unit", help="scope to one unit workspace id")
    ap.add_argument("--dump", action="store_true", help="print the tree as text, no curses")
    ap.add_argument("--split", action="store_true", help="open the map in a new pane right of this one")
    a = ap.parse_args(argv)
    try:
        if a.dump:
            return dump(a.unit)
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
        curses.wrapper(setup, a.unit)
    except KeyboardInterrupt:
        pass
    finally:
        mark_view(own, False)
    return 0
