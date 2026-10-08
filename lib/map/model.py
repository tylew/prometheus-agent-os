# ---
# name: map.model
# description: Pure model for the prometheus map — a Herdr snapshot (workspace + pane tokens from source prometheus) plus a read-only dispatch.json overlay (outbox held counts, proposals, last_change ages) → a Tree of NodeViews with per-unit activity stats, and drill-down levels (system: seat → units · unit: PM → its agents · control: seat → librarian, runners, proposals, strays). No I/O.
# usage: imported (from map import model); tree = model.build(snapshot, state, own_pane=...); model.level(tree, path) → (hub, spokes)
# ---
# Tree building adapted from Horchestra's agentmap.py (https://github.com/SimoneDaniotti/horchestra),
# MIT License, Copyright (c) 2026 Simone Daniotti.
from __future__ import annotations

import time

from .views import STATUS, NodeView, count_line

TOP_ROLES = ("seat", "librarian")
CHILD_ROLES = ("planner", "implementor", "reviewer")
ROLE_ORDER = {r: i for i, r in enumerate(("seat", "librarian", "pm") + CHILD_ROLES)}
CONTROL = "control"  # path element for the seat's own level


class Tree:
    def __init__(self):
        self.nodes = {}  # key -> NodeView
        self.raw = {}  # key -> source dict (pane, workspace, proposal, ...)
        self.panes = []  # agent panes shown, for activity / watching
        self.seat = None  # seat pane key
        self.units = []  # unit node keys, in display order
        self.pm = {}  # unit key -> PM pane key
        self.workers = {}  # unit key -> [pane keys under the PM]
        self.control = []  # keys on the seat's level
        self.proposals = []
        self.dispatcher = "stopped"
        self.held = 0
        self.counts = {}  # agent status -> n, over every shown agent
        self.needs = 0


def tokens(item):
    t = (item or {}).get("tokens")
    return t if isinstance(t, dict) else {}


def csv(val):
    return [v.strip() for v in (val or "").split(",") if v.strip()]


def needs_you(pane):
    status = pane.get("agent_status")
    return (tokens(pane).get("needs") == "1" and status != "working") or status == "blocked"


def detail_of(pane, needs):
    t = tokens(pane)
    if t.get("status"):
        return t["status"]
    if needs:
        return "needs you"
    if t.get("item") or t.get("pr"):
        return " · ".join(v for v in (t.get("item"), t.get("pr")) if v)
    return pane.get("terminal_title_stripped") or ""


def ago(seconds):
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}"
    return f"{seconds // 86400}d"


def agent_name(pane, tab_label):
    t = tokens(pane)
    role = t.get("role") or pane.get("agent") or "shell"
    if role in CHILD_ROLES or role in ("runner", "configurator"):
        if tab_label and not tab_label.isdigit():
            return tab_label
        return f"{role}-{t['item']}" if t.get("item") else role
    return role


def links(t, story_slug=None):
    """[(label, url or None)] for a unit's stories then PRs."""
    out = []
    for story in csv(t.get("stories")):
        num = story.split("-", 1)[-1]
        url = f"https://app.shortcut.com/{story_slug}/story/{num}" if story_slug and num.isdigit() else None
        out.append((story, url))
    prs = csv(t.get("prs"))
    repos = {p.split("#", 1)[0] for p in prs}
    for pr in prs:
        repo, _, num = pr.partition("#")
        label = f"#{num}" if len(repos) == 1 else f"{repo.rsplit('/', 1)[-1]}#{num}"
        out.append((label, f"https://github.com/{repo}/pull/{num}" if repo.count("/") == 1 and num.isdigit() else None))
    return out


def build(snap, state=None, own_pane="", here_tab="", now=None, own_workspace="", story_slug=None):
    """Snapshot + dispatcher state → Tree."""
    now = time.time() if now is None else now
    state = state if isinstance(state, dict) else {}
    outbox = state.get("outbox") if isinstance(state.get("outbox"), dict) else {}
    last_change = state.get("last_change") if isinstance(state.get("last_change"), dict) else {}
    tree = Tree()
    tree.proposals = [p for p in state.get("proposals") or [] if isinstance(p, dict)]

    workspaces = [w for w in snap.get("workspaces") or [] if isinstance(w, dict)]
    ws_by_id = {w.get("workspace_id"): w for w in workspaces}
    tab_label = {t.get("tab_id"): t.get("label") or "" for t in snap.get("tabs") or [] if isinstance(t, dict)}
    units = {w["workspace_id"]: w for w in workspaces if tokens(w).get("unit")}

    def role_of(p):
        return tokens(p).get("role")

    def add(node, raw):
        tree.nodes[node.key] = node
        tree.raw[node.key] = raw
        return node

    panes = []
    for p in snap.get("panes") or []:
        if not isinstance(p, dict) or not p.get("pane_id"):
            continue
        t = tokens(p)
        if p["pane_id"] == own_pane or t.get("view"):
            continue
        if t.get("role") or (p.get("agent") and p.get("workspace_id") in units):
            panes.append(p)

    # control workspace: the map's own when it holds a seat, else the running dispatcher's, else a seat's.
    # Another instance's control roles (a trial beside the real one) are left out.
    seat_ws = {p.get("workspace_id") for p in panes if role_of(p) == "seat"}
    control = ws_by_id.get(own_workspace) if own_workspace in seat_ws else None
    control = control or next((w for w in workspaces if tokens(w).get("dispatcher") == "running"), None)
    if control is None:
        seat = next((p for p in panes if role_of(p) == "seat"), None)
        control = ws_by_id.get(seat.get("workspace_id")) if seat else None
    if control is not None:
        cid = control.get("workspace_id")
        panes = [p for p in panes if role_of(p) not in TOP_ROLES + ("runner", "configurator") or p.get("workspace_id") == cid]
    tree.panes = panes
    tree.dispatcher = "running" if tokens(control).get("dispatcher") == "running" else "stopped"

    for p in panes:
        needs = needs_you(p)
        held = outbox.get(p["pane_id"])
        kind = "seat" if role_of(p) == "seat" else (p.get("agent") or "shell")
        node = NodeView(p["pane_id"], agent_name(p, tab_label.get(p.get("tab_id"))), kind,
                        p.get("agent_status"), detail_of(p, needs), needs=needs,
                        here=bool(here_tab) and p.get("tab_id") == here_tab,
                        held=len(held) if isinstance(held, list) else 0)
        add(node, p)
        tree.counts[node.status] = tree.counts.get(node.status, 0) + 1
        tree.needs += needs
        tree.held += node.held

    def order(p):
        return (ROLE_ORDER.get(role_of(p), 99), tree.nodes[p["pane_id"]].name.lower(), p["pane_id"])

    seat = next((p for p in sorted(panes, key=order) if role_of(p) == "seat"), None)
    tree.seat = seat["pane_id"] if seat else None

    for wid in sorted(units, key=lambda w: (tokens(units[w]).get("unit") or "", w)):
        w = units[wid]
        t = tokens(w)
        key = "unit:" + wid
        mine = sorted((p for p in panes if p.get("workspace_id") == wid and role_of(p) not in TOP_ROLES),
                      key=order)
        pm = next((p for p in mine if role_of(p) == "pm"), None)
        agents = [tree.nodes[p["pane_id"]] for p in mine]
        counts = {}
        for a in agents:
            counts[a.status] = counts.get(a.status, 0) + 1
        status = "working" if counts.get("working") else "blocked" if counts.get("blocked") else \
            "idle" if agents else "unknown"
        node = NodeView(key, t.get("unit"), "unit", status,
                        " / ".join(v for v in (", ".join(csv(t.get("prs"))), ", ".join(csv(t.get("stories"))))
                                   if v))
        node.sub = " · ".join(v for v in (t.get("kind"), t.get("stage")) if v)
        node.counts = counts
        node.agents = agents
        node.links = links(t, story_slug)
        node.flag = sum(a.needs for a in agents)
        node.held = sum(a.held for a in agents)
        changed = last_change.get(t.get("unit"))
        if isinstance(changed, (int, float)):
            node.age = ago(now - changed)
        add(node, w)
        tree.units.append(key)
        tree.pm[key] = pm["pane_id"] if pm else None
        tree.workers[key] = [p["pane_id"] for p in mine if p is not pm]

    for p in sorted(panes, key=order):
        role = role_of(p)
        if p is seat:
            continue
        if role in TOP_ROLES + ("runner", "configurator") or p.get("workspace_id") not in units:
            tree.control.append(p["pane_id"])
    for prop in tree.proposals:
        pid = prop.get("pid") or prop.get("id") or "?"
        what = " · ".join(v for v in (prop.get("kind"), prop.get("project")) if v)
        subj = ", ".join((prop.get("prs") or []) + (prop.get("stories") or []))
        node = NodeView("proposal:" + str(pid), f"{pid} {prop.get('name') or prop.get('id') or ''}".strip(),
                        "proposal", "waiting", " — ".join(v for v in (what, subj) if v), needs=True)
        add(node, prop)
        tree.control.append(node.key)

    if seat:
        node = tree.nodes[tree.seat]
        node.flag = sum(tree.nodes[k].needs for k in tree.control)
        n = len(units)
        node.sub = f"{n} unit{'s' * (n != 1)}"
        node.detail = tokens(seat).get("status") or node.sub
    return tree


def seat_node(tree):
    """The system hub: the seat, or a stand-in when no seat is running."""
    if tree.seat:
        return tree.nodes[tree.seat]
    node = tree.nodes.get(CONTROL)
    if node is None:
        node = NodeView(CONTROL, "no seat", "seat", "unknown", "start one with launch.sh seat")
        tree.nodes[CONTROL] = node
        tree.raw[CONTROL] = {}
    node.flag = sum(tree.nodes[k].needs for k in tree.control)
    return node


def level(tree, path):
    """(hub, spokes) for a breadcrumb path: [] system · [CONTROL] the seat's level · ["unit:<ws>"] a unit."""
    if not path:
        return seat_node(tree), [tree.nodes[k] for k in tree.units]
    top = path[-1]
    if top == CONTROL:
        return seat_node(tree), [tree.nodes[k] for k in tree.control]
    if top in tree.units:
        pm = tree.pm.get(top)
        hub = tree.nodes[pm] if pm else tree.nodes[top]
        return hub, [tree.nodes[k] for k in tree.workers[top]]
    return None, []


def drill_path(tree, key):
    """The path that drilling into `key` opens, or None for a leaf."""
    if key in tree.units:
        return key
    if key == CONTROL or (key and key == tree.seat):
        return CONTROL
    return None


def preview_target(tree, key):
    """The pane a node previews: an agent itself, a unit its PM, the seat itself."""
    if key in tree.units:
        return tree.pm.get(key)
    if key in tree.nodes and key not in (CONTROL,) and not key.startswith("proposal:"):
        return key
    return None


def unit_of(tree, key):
    return next((u for u in tree.units if key == tree.pm.get(u) or key in tree.workers[u]), None)


def to_text(tree):
    """Every level as plain indented text (for --dump and tests)."""
    lines = [header_text(tree)]

    def row(node, lead):
        glyph, word = STATUS[node.status]
        if node.kind == "unit":
            bits = [f"{lead}◼ {node.name}"]
            if node.sub:
                bits.append(f"({node.sub})")
            if node.counts:
                bits.append(count_line(node.counts))
        else:
            bits = [f"{lead}{glyph} {node.name} [{word}]"]
            if node.needs:
                bits.append("! needs you")
        if node.flag and not node.needs:
            bits.append(f"!{node.flag}")
        if node.held:
            bits.append(f"✉{node.held}")
        if node.age:
            bits.append(f"{node.age} ago")
        if node.detail:
            bits.append("— " + node.detail)
        lines.append("  ".join(bits))
        if node.kind == "unit":
            pad = "   " if lead.startswith("├") else "   "
            for a in node.agents:
                lines.append(f"{pad}  · {a.name} [{STATUS[a.status][1]}]" + (f" — {a.detail}" if a.detail else ""))
            if node.links:
                lines.append(f"{pad}  ↗ " + "  ".join(label for label, _ in node.links))

    def block(hub, spokes, title=None):
        if title:
            lines.append("")
            lines.append(title)
        row(hub, "")
        for i, s in enumerate(spokes):
            row(s, "└─ " if i == len(spokes) - 1 else "├─ ")

    block(*level(tree, []))
    hub, spokes = level(tree, [CONTROL])
    if spokes:
        block(hub, spokes, "[control]")
    for u in tree.units:
        block(*level(tree, [u]), f"[{tree.nodes[u].name}]")
    return "\n".join(lines)


def header_text(tree):
    agents = sum(tree.counts.values())
    bits = [f"dispatcher {tree.dispatcher}", f"{agents} agent{'s' * (agents != 1)}"]
    if tree.counts:
        bits.append(count_line(tree.counts))
    if tree.needs:
        bits.append(f"!{tree.needs}")
    if tree.proposals:
        bits.append(f"?{len(tree.proposals)}")
    if tree.held:
        bits.append(f"✉{tree.held}")
    return " · ".join(bits)
