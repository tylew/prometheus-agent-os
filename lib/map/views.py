# ---
# name: map.views
# description: Pure layout for the prometheus map — one drill-down level drawn as a hub box over a fan of spoke boxes (wrapping into rows, never wider than the screen), with distinct seat (heavy), unit workspace (double) and agent (rounded) boxes, live working edges — drawn onto a Canvas of (char, style) cells so it tests as plain text.
# usage: imported (from map import views); views.render_level(hub, spokes, width, spark={key: str})
# ---
# Canvas and edge animation ported from Horchestra's views.py (https://github.com/SimoneDaniotti/horchestra),
# MIT License, Copyright (c) 2026 Simone Daniotti.
from __future__ import annotations

# kind -> (icon, style)
KINDS = {
    "claude": ("✻", "kind:claude"),
    "shell": ("$", "dim"),
    "seat": ("◉", "accent"),
    "unit": ("◼", "accent"),
    "proposal": ("?", "needs"),
}
DEFAULT_KIND = ("▪", "kind:other")

# status -> (glyph, short word)
STATUS = {
    "working": ("●", "working"),
    "blocked": ("▲", "blocked"),
    "done": ("✓", "done"),
    "idle": ("○", "idle"),
    "running": ("▶", "running"),
    "stopped": ("■", "stopped"),
    "waiting": ("?", "waiting"),
    "unknown": ("·", "?"),
}

# kind -> (top-left, top, top-right, side, bottom-left, bottom-right, bottom tee, top tee)
HEAVY_BOX = ("┏", "━", "┓", "┃", "┗", "┛", "┳", "┻")
DOUBLE_BOX = ("╔", "═", "╗", "║", "╚", "╝", "╤", "╧")
ROUND_BOX = ("╭", "─", "╮", "│", "╰", "╯", "┬", "┴")
BORDERS = {"seat": HEAVY_BOX, "unit": DOUBLE_BOX}

GAP = 2
GUTTER = 3  # wrapped rows start right of the trunk
SPOKE_MIN, SPOKE_MAX = 18, 40
HUB_MIN, HUB_MAX = 26, 56


class NodeView:
    """Display data for one node, independent of Herdr's JSON."""

    __slots__ = ("key", "name", "kind", "status", "detail", "needs", "here", "held", "flag",
                 "selected", "sub", "counts", "age")

    def __init__(self, key, name, kind, status, detail="", needs=False, here=False, held=0):
        self.key = key
        self.name = name or key
        self.kind = kind
        self.status = status if status in STATUS else "unknown"
        self.detail = detail
        self.needs = needs
        self.here = here
        self.held = held
        self.flag = 0  # needs-you below this node
        self.selected = False
        self.sub = ""  # unit: kind · stage; seat: unit count
        self.counts = {}  # unit: agent status -> n
        self.age = ""  # unit: since the dispatcher's last change

    @property
    def icon(self):
        return KINDS.get(self.kind, DEFAULT_KIND)


def marks(node):
    """Badges: `!N` needs-you below, `✉N` held in the dispatcher outbox."""
    out = []
    if node.flag and not node.needs:
        out.append(f"!{node.flag}")
    if node.held:
        out.append(f"✉{node.held}")
    return " ".join(out)


class Canvas:
    def __init__(self, width):
        self.width = max(1, width)
        self.rows = []
        # [(child key, [(y, x), ...])]: each hub->spoke edge, hub end first.
        self.edges = []

    def ensure(self, y):
        while len(self.rows) <= y:
            self.rows.append([[" ", None] for _ in range(self.width)])

    def put(self, y, x, text, style=None):
        if y < 0:
            return
        self.ensure(y)
        row = self.rows[y]
        for i, ch in enumerate(text):
            if 0 <= x + i < self.width:
                row[x + i] = [ch, style]

    def get(self, y, x):
        if 0 <= y < len(self.rows) and 0 <= x < self.width:
            return self.rows[y][x][0]
        return " "

    def runs(self, y, x0=0, x1=None):
        """[(x, text, style)] for row y between columns x0 and x1."""
        if y >= len(self.rows):
            return []
        row = self.rows[y][x0:x1]
        out = []
        for i, (ch, style) in enumerate(row):
            if out and out[-1][2] == style:
                out[-1][1] += ch
            else:
                out.append([x0 + i, ch, style])
        return [tuple(r) for r in out]

    def text(self):
        return "\n".join("".join(c[0] for c in row).rstrip() for row in self.rows)


def fit(text, width):
    if width <= 0:
        return ""
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def _border_style(node):
    if node.selected:
        return "sel_here" if node.here else "sel"
    if node.needs or node.flag:
        return "needs"
    return "here" if node.here else "border"


def content(node, spark=None):
    """[(text, style)] lines inside a node's box."""
    glyph, word = STATUS[node.status]
    icon = node.icon[0]
    name_style = "selname" if node.selected else "name"
    badge = marks(node)
    if node.kind == "unit":
        stats = " ".join(v for v in (count_line(node.counts), badge, node.age) if v) or "no agents"
        lines = [(f"{icon} {node.name}", name_style), (node.sub or node.detail, "dim"),
                 (stats, "needs" if node.flag else "status:" + node.status)]
        lines.append((spark or "", "spark"))
        return lines
    if node.kind == "seat":
        right = " ".join(v for v in (f"{glyph} {word}", badge) if v)
        return [(f"{icon} {node.name}", name_style), (right, "needs" if node.flag else "status:" + node.status),
                (node.detail or node.sub, "dim")]
    head = f"{glyph} {node.name}"
    if badge:
        head += " " + badge
    detail = ("! " + node.detail) if node.needs else node.detail
    return [(head, name_style), (detail, "needs" if node.needs else "dim")]


COUNT_ORDER = ("working", "blocked", "idle", "done")


def count_line(counts):
    return " ".join(f"{STATUS[s][0]}{counts[s]}" for s in COUNT_ORDER if counts.get(s))


def box_height(node):
    return len(content(node)) + 2


def draw_box(canvas, node, y, x, w, spark=None, tee_top=None, tee_bottom=None):
    tl, h, tr, side, bl, br, tb, tt = BORDERS.get(node.kind, ROUND_BOX)
    style = _border_style(node)
    inner = w - 2
    lines = content(node, spark)
    canvas.put(y, x, tl + h * inner + tr, style)
    for i, (text, text_style) in enumerate(lines):
        row = y + 1 + i
        canvas.put(row, x, side + " " * inner + side, style)
        if i == 0 and node.kind not in ("unit", "seat"):
            glyph = text[0]
            canvas.put(row, x + 2, glyph, "status:" + node.status)
            canvas.put(row, x + 4, fit(text[2:], inner - 3), text_style)
        else:
            canvas.put(row, x + 2, fit(text, inner - 2), text_style)
    bottom = y + 1 + len(lines)
    canvas.put(bottom, x, bl + h * inner + br, style)
    if tee_top is not None:
        canvas.put(y, tee_top, tt, style)
    if tee_bottom is not None:
        canvas.put(bottom, tee_bottom, tb, style)
    return bottom


def spoke_width(spokes, width):
    longest = max((len(s.name) + 6 for s in spokes), default=SPOKE_MIN)
    return max(10, min(max(SPOKE_MIN, min(SPOKE_MAX, longest)), width - GUTTER - 1))


def per_row(spokes, width):
    bw = spoke_width(spokes, width)
    return max(1, (width - GUTTER + GAP) // (bw + GAP))


def render_level(hub, spokes, width, spark=None):
    """Hub box over its spokes. One row of spokes fans out centered under the hub; more wrap into
    left-aligned rows fed by a trunk down the left gutter. Returns (canvas, boxes: key -> (y0, y1, x0, x1))."""
    spark = spark or {}
    canvas, boxes = Canvas(width), {}
    bw = spoke_width(spokes, width)
    n = per_row(spokes, width)
    rows = [spokes[i:i + n] for i in range(0, len(spokes), n)]
    hub_w = min(width - 2, HUB_MAX, max(HUB_MIN, len(hub.name) + 8, len(hub.detail or "") + 6))
    single = len(rows) <= 1
    if single:
        row_w = len(spokes) * bw + GAP * max(0, len(spokes) - 1)
        span = max(row_w, hub_w)
        left = max(0, (width - span) // 2)
        hub_x = left + (span - hub_w) // 2
        trunk = hub_x + hub_w // 2
        first_x = left + (span - row_w) // 2
    else:
        hub_x, trunk, first_x = 0, 1, GUTTER
    hub_bottom = draw_box(canvas, hub, 0, hub_x, hub_w, spark.get(hub.key),
                          tee_bottom=trunk if spokes else None)
    boxes[hub.key] = (0, hub_bottom, hub_x, hub_x + hub_w - 1)
    if not spokes:
        return canvas, boxes
    canvas.put(hub_bottom + 1, trunk, "│", "rail")
    y = hub_bottom + 2  # first bus line
    trunk_path = [(hub_bottom, trunk), (hub_bottom + 1, trunk)]
    for r, row in enumerate(rows):
        centers = [first_x + i * (bw + GAP) + bw // 2 for i in range(len(row))]
        lo, hi = min(centers + [trunk]), max(centers + [trunk])
        canvas.put(y, lo, "─" * (hi - lo + 1), "rail")
        for c in centers:
            canvas.put(y, c, "┬", "rail")
        last_row = r == len(rows) - 1
        if single:
            if len(centers) == 1 and centers[0] == trunk:
                canvas.put(y, trunk, "│", "rail")
            else:
                canvas.put(y, lo, "┌" if lo in centers else "└", "rail")
                canvas.put(y, hi, "┐" if hi in centers else "┘", "rail")
                canvas.put(y, trunk, "┼" if trunk in centers else "┴", "rail")
        else:
            canvas.put(y, trunk, "└" if last_row else "├", "rail")
            canvas.put(y, hi, "┐", "rail")
        height = 0
        for node, c in zip(row, centers):
            x = c - bw // 2
            bottom = draw_box(canvas, node, y + 1, x, bw, spark.get(node.key), tee_top=c)
            boxes[node.key] = (y + 1, bottom, x, x + bw - 1)
            height = max(height, bottom - y)
            step = 1 if c >= trunk else -1
            path = trunk_path + [(y, bx) for bx in range(trunk, c + step, step)] + [(y + 1, c)]
            canvas.edges.append((node.key, path))
        if not last_row:
            for ry in range(y + 1, y + height + 1):
                canvas.put(ry, trunk, "│", "rail")
            trunk_path = trunk_path + [(ry, trunk) for ry in range(y, y + height + 1)]
        y += height + 1
    return canvas, boxes


# ---- live edges ------------------------------------------------------------

HEAVY = str.maketrans("│─┬┴┼┌┐└┘├┤╭╮╰╯", "┃━┳┻╋┏┓┗┛┣┫┏┓┗┛")
PULSE_PERIOD = 6  # cells between pulses
PULSE_LENGTH = 2


def animate_edges(canvas, active, frame):
    """Light up the edges into `active` spoke keys; a pulse runs hub -> spoke.

    Edge cells take the "flow" style; every PULSE_PERIOD cells a short run
    turns heavy in "pulse" style, shifted one cell per frame.
    """
    lit = {}
    for key, path in canvas.edges:
        if key not in active:
            continue
        for i, cell in enumerate(path):
            pulse = (i - frame) % PULSE_PERIOD < PULSE_LENGTH
            lit[cell] = lit.get(cell, False) or pulse
    for (y, x), pulse in lit.items():
        if 0 <= y < len(canvas.rows) and 0 <= x < canvas.width:
            ch = canvas.rows[y][x][0]
            if ch == " " or canvas.rows[y][x][1] not in ("rail", "flow", "pulse"):
                continue
            canvas.rows[y][x] = [ch.translate(HEAVY), "pulse"] if pulse else [ch, "flow"]
    return bool(lit)
