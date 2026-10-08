# ---
# name: map.views
# description: Pure layout for the prometheus map — the seat level as the seat hub over one compact line per unit (epic name · id, PM state, story count, PRs by status mark, needs-you, held, age, activity); a drill-down level as a hub box over a fan of spoke boxes (wrapping into rows, never wider than the screen), with distinct seat (heavy), unit (double), story group (square: its PRs with status marks and the agents working it, each agent row selectable) and agent (rounded) boxes, live working edges, agent logos and state marks from the radar icon font when enabled — drawn onto a Canvas of (char, style) cells so it tests as plain text.
# usage: imported (from map import views); views.render_seat(hub, units, width) · views.render_level(hub, spokes, width, spark={key: str})
# ---
# Canvas and edge animation ported from Horchestra's views.py (https://github.com/SimoneDaniotti/horchestra),
# MIT License, Copyright (c) 2026 Simone Daniotti.
from __future__ import annotations

from . import icons

# kind -> (icon, style)
KINDS = {
    "claude": ("✻", "kind:claude"),
    "shell": ("$", "dim"),
    "seat": ("◉", "accent"),
    "unit": ("◼", "accent"),
    "proposal": ("?", "needs"),
    "story": ("▣", "accent"),
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
SQUARE_BOX = ("┌", "─", "┐", "│", "└", "┘", "┬", "┴")
BORDERS = {"seat": HEAVY_BOX, "unit": DOUBLE_BOX, "story": SQUARE_BOX}

# PR status marks, in the seat line's count order
PR_MARKS = ("✓", "✗", "⟳", "◌", "●", "!")
MARK_STYLE = {"✓": "status:done", "✗": "needs", "⟳": "status:working", "◌": "dim", "●": "accent", "!": "needs",
              "·": "dim", "–": "dim"}

FONT = {"on": False}  # set by the app once it knows the radar icon font is installed
MAX_AGENT_LINES = 5

GAP = 2
GUTTER = 3  # wrapped rows start right of the trunk
SPOKE_MIN, SPOKE_MAX = 18, 40
GROUP_MIN, GROUP_MAX = 36, 56  # story group boxes
HUB_MIN, HUB_MAX = 26, 56


class NodeView:
    """Display data for one node, independent of Herdr's JSON."""

    __slots__ = ("key", "name", "kind", "status", "detail", "needs", "here", "held", "flag",
                 "selected", "sub", "counts", "age", "agents", "links", "prs", "rows", "ident", "unit_kind",
                 "stories", "lead")

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
        self.agents = []  # unit: its PM then workers (NodeViews)
        self.links = []  # unit: [(label, url or None)] stories then PRs
        self.prs = []  # unit / story group: [{ref, label, url, mark, author, stories}]
        self.rows = []  # unit: [(agent NodeView, story or None, PR label or None)], PM first
        self.ident = ""  # unit: Shortcut epic id
        self.unit_kind = ""  # unit: epic · story · story-set · goal-set · review
        self.stories = []  # unit: its stories, in group order
        self.lead = None  # unit: its PM's NodeView

    @property
    def icon(self):
        return KINDS.get(self.kind, DEFAULT_KIND)


def use_font(on):
    FONT["on"] = bool(on)


def logo(kind):
    if FONT["on"] and kind in icons.LOGOS:
        return icons.LOGOS[kind]
    return KINDS.get(kind, DEFAULT_KIND)[0]


def glyph(status):
    if FONT["on"] and status in icons.STATES:
        return icons.STATES[status]
    return STATUS[status][0]


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
        self.links = []  # [(y, x0, x1, url)] clickable link text
        self.keyed = []  # [(key, y, x0, x1)] selectable rows inside a box (agents in a story group)

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


def agent_line(agent, name_style="name"):
    """Segments for one agent: logo, state mark, name, its status line."""
    head = [(logo(agent.kind), agent.icon[1]), (" ", None), (glyph(agent.status), "status:" + agent.status),
            (" ", None), (agent.name, name_style)]
    badge = marks(agent)
    if badge:
        head += [(" " + badge, "needs" if agent.flag else "accent")]
    if agent.needs:
        head += [("  ! " + (agent.detail or "needs you"), "needs")]
    elif agent.detail:
        head += [("  " + agent.detail, "dim")]
    return head


class Wrap(list):
    """A line whose segments wrap onto further rows instead of being cut."""


class Row(list):
    """A line that is itself selectable: an agent inside a story group."""

    def __init__(self, segments, key):
        super().__init__(segments)
        self.key = key


def mark_counts(prs):
    counts = {}
    for p in prs:
        counts[p["mark"]] = counts.get(p["mark"], 0) + 1
    return counts


def mark_line(prs):
    """`✓a ✗b ⟳c ◌d ●e !f`, nonzero counts only."""
    counts = mark_counts(prs)
    return " ".join(f"{m}{counts[m]}" for m in PR_MARKS if counts.get(m))


def seat_line(node, spark=None):
    """Segments for a unit's compact seat line: `◼ <name> · <epic id>  <pm glyph> pm  <n> sc · <PR marks>
    ⚑<needs>  ✉<held>  <age>  <spark>`. An older unit shows its kind where an epic shows its id."""
    out = [(f"{node.icon[0]} ", "accent"), (node.name, "selname" if node.selected else "name")]
    tag = node.ident if node.unit_kind == "epic" else node.unit_kind
    if tag:
        out.append((f" · {tag}", "dim"))
    out.append(("  ", None))
    if node.lead:
        out += [(glyph(node.lead.status), "status:" + node.lead.status), (" pm", "dim")]
    else:
        out.append(("· no pm", "dim"))
    out.append((f"  {len(node.stories)} sc", "dim"))
    counts = mark_counts(node.prs)
    shown = [m for m in PR_MARKS if counts.get(m)]
    if shown:
        out.append((" ·", "dim"))
        for m in shown:
            out += [(" ", None), (f"{m}{counts[m]}", MARK_STYLE[m])]
    if node.flag:
        out.append((f"  ⚑{node.flag}", "needs"))
    if node.held:
        out.append((f"  ✉{node.held}", "accent"))
    if node.age:
        out.append((f"  {node.age}", "dim"))
    if spark and spark.strip():
        out.append((f"  {spark}", "spark"))
    return out


def pr_segments(prs):
    """A story group's PRs: `<mark> #<n> [@author]`, wrapping, each label a link."""
    out = Wrap()
    for p in prs:
        if out:
            out.append(("  ", None))
        out += [(p["mark"] + " ", MARK_STYLE.get(p["mark"], "dim")), (p["label"], "link" if p["url"] else "name",
                                                                       p["url"])]
        if p["author"]:
            out.append((" @" + p["author"], "dim"))
    return out


def link_line(links):
    out = Wrap()
    for i, (label, url) in enumerate(links[:9]):
        if out:
            out.append(("  ", None))
        out += [(f"{i + 1} ", "dim"), (label, "link" if url else "dim", url)]
    return out


def content(node, spark=None, links=None, title=None):
    """Lines inside a node's box; each is [(text, style[, url])]."""
    glyph_, word = glyph(node.status), STATUS[node.status][1]
    name_style = "selname" if node.selected else "name"
    badge = marks(node)
    if node.kind == "story":
        lines = [[(f"{node.icon[0]} {node.name}", "name"), (f" {node.sub}" if node.sub else "", "accent"),
                  (f"  {badge}" if badge else "", "needs" if node.flag else "accent")]]
        lines.append(pr_segments(node.prs) if node.prs else [("no PRs", "dim")])
        for a in node.agents:
            lines.append(Row(agent_line(a, "selname" if a.selected else "name"), a.key))
        if not node.agents:
            lines.append([("(no agent)", "dim")])
        return lines
    if node.kind == "unit":
        shown = node.agents[:MAX_AGENT_LINES]
        hidden = len(node.agents) > len(shown)
        stats = " ".join(v for v in (count_line(node.counts) if hidden or not node.agents else "", badge,
                                     node.age) if v) or ("" if node.agents else "no agents")
        lines = [[(f"{node.icon[0]} {node.name}", name_style)],
                 [(node.sub or "", "dim"), ("  " if node.sub else "", None),
                  (stats, "needs" if node.flag else "status:" + node.status)]]
        lines += [agent_line(a) for a in shown]
        if hidden:
            lines.append([(f"+{len(node.agents) - len(shown)} more", "dim")])
        if spark and spark.strip():
            lines.append([(spark, "spark")])
        if node.links:
            lines.append(link_line(node.links))
        return lines
    if node.kind == "seat":
        right = " ".join(v for v in (f"{glyph_} {word}", badge) if v)
        return [[(f"{node.icon[0]} {node.name}", name_style)],
                [(right, "needs" if node.flag else "status:" + node.status)],
                [(node.detail or node.sub, "dim")]]
    head = [(logo(node.kind), node.icon[1]), (" ", None), (glyph_, "status:" + node.status), (" ", None),
            (node.name, name_style)]
    if badge:
        head.append((" " + badge, "needs" if node.flag else "accent"))
    detail = ("! " + node.detail) if node.needs else node.detail
    lines = [head, [(detail, "needs" if node.needs else "dim")]]
    if title:
        lines.insert(1, [(title, "accent")])
    if links:
        lines.append(link_line(links))
    return lines


COUNT_ORDER = ("working", "blocked", "idle", "done")


def count_line(counts):
    return " ".join(f"{STATUS[s][0]}{counts[s]}" for s in COUNT_ORDER if counts.get(s))


def put_segments(canvas, row, cx, end, segments):
    """Draw [(text, style[, url])] from column cx, cut at `end`; links are recorded. Returns the next column."""
    for seg in segments:
        text, seg_style = seg[0], seg[1]
        if not text or cx >= end:
            continue
        shown = fit(text, end - cx)
        canvas.put(row, cx, shown, seg_style)
        if len(seg) > 2 and seg[2]:
            canvas.links.append((row, cx, cx + len(shown) - 1, seg[2]))
        cx += len(shown)
    return cx


def draw_box(canvas, node, y, x, w, spark=None, tee_top=None, tee_bottom=None, links=None, title=None):
    tl, h, tr, side, bl, br, tb, tt = BORDERS.get(node.kind, ROUND_BOX)
    if node.kind == "story":
        node.selected = any(a.selected for a in node.agents)
    style = _border_style(node)
    inner = w - 2
    lines = []
    for line in content(node, spark, links, title):
        lines += wrap_segments(line, inner - 2) if isinstance(line, Wrap) else [line]
    canvas.put(y, x, tl + h * inner + tr, style)
    for i, segments in enumerate(lines):
        row = y + 1 + i
        canvas.put(row, x, side + " " * inner + side, style)
        put_segments(canvas, row, x + 2, x + w - 2, segments)
        if isinstance(segments, Row):
            canvas.keyed.append((segments.key, row, x + 1, x + w - 2))
    bottom = y + 1 + len(lines)
    canvas.put(bottom, x, bl + h * inner + br, style)
    if tee_top is not None:
        canvas.put(y, tee_top, tt, style)
    if tee_bottom is not None:
        canvas.put(bottom, tee_bottom, tb, style)
    return bottom


def wrap_segments(segments, width):
    """Break a Wrap line into rows at its gaps; a number stays with the label after it."""
    items, cur = [], []
    for seg in segments:
        if seg[0] == "  " and cur:
            items.append(cur)
            cur = []
        else:
            cur.append(seg)
    if cur:
        items.append(cur)
    rows, row, used = [], [], 0
    for item in items:
        size = sum(len(s[0]) for s in item)
        if row and used + 2 + size > width:
            rows.append(row)
            row, used = [], 0
        if row:
            row.append(("  ", None))
            used += 2
        row += item
        used += size
    if row:
        rows.append(row)
    return rows or [[]]


def spoke_width(spokes, width):
    if any(s.kind == "story" for s in spokes):
        longest = max([GROUP_MIN] + [len(a.name) + len(a.detail or "") + 10 for s in spokes for a in s.agents])
        return max(10, min(GROUP_MAX, longest, width - GUTTER - 1))
    longest = max((len(s.name) + 9 if s.kind != "unit" else max(len(s.name) + 6, 36) for s in spokes),
                  default=SPOKE_MIN)
    return max(10, min(max(SPOKE_MIN, min(SPOKE_MAX, longest)), width - GUTTER - 1))


def per_row(spokes, width):
    bw = spoke_width(spokes, width)
    return max(1, (width - GUTTER + GAP) // (bw + GAP))


def render_seat(hub, units, width, spark=None):
    """The seat level: the seat hub over one compact line per unit, fed by a trunk down the left.
    Returns (canvas, boxes: key -> (y0, y1, x0, x1)); a unit's box is its line."""
    spark = spark or {}
    canvas, boxes = Canvas(width), {}
    hub_w = min(width - 2, HUB_MAX, max(HUB_MIN, len(hub.name) + 8, len(hub.detail or "") + 6))
    bottom = draw_box(canvas, hub, 0, 0, hub_w, spark.get(hub.key), tee_bottom=1 if units else None)
    boxes[hub.key] = (0, bottom, 0, hub_w - 1)
    path = [(bottom, 1)]
    for i, unit in enumerate(units):
        y = bottom + 1 + i
        canvas.put(y, 1, ("└" if i == len(units) - 1 else "├") + "─", "rail")
        if unit.selected:
            canvas.put(y, 3, "▸", "sel")
        line = seat_line(unit, spark.get(unit.key))
        if sum(len(seg[0]) for seg in line) > width - 6:
            line = seat_line(unit)  # the activity cells go first when the line does not fit
        put_segments(canvas, y, 5, width - 1, line)
        boxes[unit.key] = (y, y, 3, width - 1)
        canvas.edges.append((unit.key, path + [(y, 1), (y, 2)]))
        path = path + [(y, 1)]
    return canvas, boxes


def render_level(hub, spokes, width, spark=None, hub_links=None, hub_title=None):
    """Hub box over its spokes. One row of spokes fans out centered under the hub; more wrap into
    left-aligned rows fed by a trunk down the left gutter. Story group spokes are not boxes of their own:
    their agent rows are. Returns (canvas, boxes: key -> (y0, y1, x0, x1))."""
    spark = spark or {}
    canvas, boxes = Canvas(width), {}
    bw = spoke_width(spokes, width)
    n = per_row(spokes, width)
    rows = [spokes[i:i + n] for i in range(0, len(spokes), n)]
    hub_w = min(width - 2, HUB_MAX, max(HUB_MIN, len(hub.name) + 8, len(hub.detail or "") + 6,
                                        len(hub_title or "") + 6))
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
                          tee_bottom=trunk if spokes else None, links=hub_links, title=hub_title)
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
            if node.kind != "story":
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
    for key, ry, x0, x1 in canvas.keyed:
        boxes[key] = (ry, ry, x0, x1)
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
