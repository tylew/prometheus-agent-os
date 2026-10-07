# ---
# name: map.model
# description: Pure tree for the prometheus map — a Herdr snapshot (workspace + pane tokens from source prometheus) plus a read-only dispatch.json overlay (outbox held counts, proposals, last_change ages) → NodeView roots. No I/O.
# usage: imported (from map import model); model.build(snapshot, state, own_pane=..., unit=...) → Tree
# ---
# Tree building adapted from Horchestra's agentmap.py (https://github.com/SimoneDaniotti/horchestra),
# MIT License, Copyright (c) 2026 Simone Daniotti.
from __future__ import annotations

import time

from .views import STATUS, NodeView

TOP_ROLES = ("seat", "librarian")
CHILD_ROLES = ("planner", "implementor", "reviewer")
ROLE_ORDER = {r: i for i, r in enumerate(("seat", "librarian", "pm") + CHILD_ROLES)}


class Tree:
    def __init__(self):
        self.roots = []
        self.nodes = {}  # key -> NodeView
        self.raw = {}  # key -> source dict (pane, workspace, proposal, ...)
        self.panes = []  # agent panes shown, for activity / watching
        self.proposals = []
        self.dispatcher = "stopped"
        self.held = 0


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
    if role in CHILD_ROLES or role == "runner":
        if tab_label and not tab_label.isdigit():
            return tab_label
        return f"{role}-{t['item']}" if t.get("item") else role
    return role


def _order(node, raw):
    role = tokens(raw.get(node.key)).get("role")
    return (ROLE_ORDER.get(role, 99), node.name.lower(), node.key)


def build(snap, state=None, own_pane="", unit=None, here_tab="", now=None, own_workspace=""):
    """Snapshot + dispatcher state → Tree. `unit` (a workspace id) scopes it to that unit."""
    now = time.time() if now is None else now
    state = state if isinstance(state, dict) else {}
    outbox = state.get("outbox") if isinstance(state.get("outbox"), dict) else {}
    last_change = state.get("last_change") if isinstance(state.get("last_change"), dict) else {}
    proposals = [p for p in state.get("proposals") or [] if isinstance(p, dict)]
    tree = Tree()
    tree.proposals = proposals

    workspaces = [w for w in snap.get("workspaces") or [] if isinstance(w, dict)]
    ws_by_id = {w.get("workspace_id"): w for w in workspaces}
    tab_label = {t.get("tab_id"): t.get("label") or "" for t in snap.get("tabs") or [] if isinstance(t, dict)}
    units = {w["workspace_id"]: w for w in workspaces if tokens(w).get("unit")}

    def add(node, raw):
        tree.nodes[node.key] = node
        tree.raw[node.key] = raw
        return node

    def attach(parent, child):
        child.parent = parent
        parent.children.append(child)

    panes = []
    for p in snap.get("panes") or []:
        if not isinstance(p, dict) or not p.get("pane_id"):
            continue
        t = tokens(p)
        if p["pane_id"] == own_pane or t.get("view"):
            continue
        if t.get("role") or (p.get("agent") and p.get("workspace_id") in units):
            panes.append(p)
    tree.panes = panes

    agent_nodes = {}
    for p in panes:
        needs = needs_you(p)
        held = outbox.get(p["pane_id"])
        node = NodeView(p["pane_id"], agent_name(p, tab_label.get(p.get("tab_id"))),
                        p.get("agent") or "shell", p.get("agent_status"), detail_of(p, needs),
                        needs=needs, here=bool(here_tab) and p.get("tab_id") == here_tab,
                        held=len(held) if isinstance(held, list) else 0)
        agent_nodes[p["pane_id"]] = add(node, p)
    tree.held = sum(n.held for n in agent_nodes.values())

    def role_of(p):
        return tokens(p).get("role")

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
        panes = [p for p in panes if role_of(p) not in TOP_ROLES + ("runner",) or p.get("workspace_id") == cid]
        tree.panes = panes
        keep = {p["pane_id"] for p in panes}
        for k in [k for k in agent_nodes if k not in keep]:
            del agent_nodes[k], tree.nodes[k], tree.raw[k]
        tree.held = sum(n.held for n in agent_nodes.values())
    tree.dispatcher = "running" if tokens(control).get("dispatcher") == "running" else "stopped"

    def unit_node(wid):
        w = units[wid]
        t = tokens(w)
        label = " · ".join(v for v in (t.get("unit"), t.get("kind"), t.get("stage")) if v)
        detail = " / ".join(v for v in (", ".join(csv(t.get("prs"))), ", ".join(csv(t.get("stories")))) if v)
        changed = last_change.get(t.get("unit"))
        if isinstance(changed, (int, float)):
            detail = (detail + " · " if detail else "") + ago(now - changed) + " ago"
        status = w.get("agent_status")
        node = add(NodeView("unit:" + wid, label, "unit", status if status in STATUS else "unknown", detail,
                            here=False), w)
        mine = sorted((p for p in panes if p.get("workspace_id") == wid and role_of(p) not in TOP_ROLES),
                      key=lambda p: _order(agent_nodes[p["pane_id"]], tree.raw))
        pm = next((p for p in mine if role_of(p) == "pm"), None)
        lead = agent_nodes[pm["pane_id"]] if pm else node
        if pm:
            attach(node, lead)
        for p in mine:
            if p is pm:
                continue
            attach(lead if role_of(p) in CHILD_ROLES else node, agent_nodes[p["pane_id"]])
        return node

    if unit:
        if unit in units:
            tree.roots = [unit_node(unit)]
    else:
        root = add(NodeView("root", "prometheus", "root", "idle"), {})
        if proposals:
            group = add(NodeView("proposals", f"proposals ({len(proposals)})", "group", "waiting",
                                 "waiting on the operator", needs=True), {"proposals": proposals})
            attach(root, group)
            for prop in proposals:
                pid = prop.get("pid") or prop.get("id") or "?"
                what = " · ".join(v for v in (prop.get("kind"), prop.get("project")) if v)
                subj = ", ".join((prop.get("prs") or []) + (prop.get("stories") or []))
                node = NodeView("proposal:" + str(pid), f"{pid} {prop.get('name') or prop.get('id') or ''}".strip(),
                                "proposal", "waiting", " — ".join(v for v in (what, subj) if v), needs=True)
                attach(group, add(node, prop))
        top = sorted((agent_nodes[p["pane_id"]] for p in panes if role_of(p) in TOP_ROLES),
                     key=lambda n: _order(n, tree.raw))
        seats = [n for n in top if tokens(tree.raw[n.key]).get("role") == "seat"]
        for n in seats:
            attach(root, n)
        # quick-work runners hang under the seat that opened them
        runners = sorted((agent_nodes[p["pane_id"]] for p in panes if role_of(p) == "runner"),
                         key=lambda n: n.name)
        for n in runners:
            attach(seats[0] if seats else root, n)
        detail = f"{len(proposals)} proposal{'s' * (len(proposals) != 1)} · {tree.held} held"
        attach(root, add(NodeView("dispatcher", "dispatcher", "dispatcher", tree.dispatcher, detail),
                         control or {}))
        for n in top:
            if n not in seats:
                attach(root, n)
        for wid in sorted(units, key=lambda w: (tokens(units[w]).get("unit") or "", w)):
            attach(root, unit_node(wid))
        stray = [agent_nodes[p["pane_id"]] for p in panes
                 if p.get("workspace_id") not in units and role_of(p) not in TOP_ROLES + ("runner",)]
        if stray:
            group = add(NodeView("unassigned", "unassigned", "group", "unknown",
                                 f"{len(stray)} pane{'s' * (len(stray) != 1)} without a unit"), {})
            attach(root, group)
            for n in sorted(stray, key=lambda n: _order(n, tree.raw)):
                attach(group, n)
        working = any(n.status == "working" for n in agent_nodes.values())
        root.status = "working" if working else "idle"
        n = len(agent_nodes)
        root.detail = f"{len(units)} unit{'s' * (len(units) != 1)} · {n} agent{'s' * (n != 1)}"
        tree.roots = [root]

    for r in tree.roots:
        _bubble(r)
    return tree


def _bubble(node):
    """Count needs-you descendants onto every ancestor (`flag`)."""
    total = 0
    for c in node.children:
        total += _bubble(c) + (1 if c.needs and c.kind != "group" else 0)
    node.flag = total
    return total


def visible_order(roots):
    out = []

    def walk(node):
        out.append(node)
        for child in node.shown_children():
            walk(child)

    for root in roots:
        walk(root)
    return out


def to_text(roots):
    """The tree as plain indented text (for --dump and tests)."""
    lines = []

    def walk(node, prefix, last, depth):
        lead = "" if depth == 0 else prefix + ("└─ " if last else "├─ ")
        glyph, word = STATUS[node.status]
        bits = [f"{lead}{glyph} {node.name} [{word}]"]
        if node.needs:
            bits.append("! needs you")
        if node.flag:
            bits.append(f"!{node.flag} below")
        if node.held:
            bits.append(f"✉{node.held} held")
        if node.detail:
            bits.append("— " + node.detail)
        lines.append("  ".join(bits))
        kids = node.children
        child_prefix = "" if depth == 0 else prefix + ("   " if last else "│  ")
        for i, c in enumerate(kids):
            walk(c, child_prefix, i == len(kids) - 1, depth + 1)

    for r in roots:
        walk(r, "", True, 0)
    return "\n".join(lines)
