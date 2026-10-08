# ---
# name: map.model
# description: Pure model for the prometheus map — a Herdr snapshot (workspace + pane tokens from source prometheus) plus a read-only dispatch.json overlay (outbox held counts, proposals, last_change ages) → a Tree of NodeViews with per-unit activity stats, and drill-down levels (system: seat → units · epic: PM over a board of every story and every agent with all the stories / PRs it touches · older unit: PM → its agents · control: seat → librarian, runners, proposals, strays). No I/O.
# usage: imported (from map import model); tree = model.build(snapshot, state, own_pane=...); model.level(tree, path) → (hub, spokes)
# ---
# Tree building adapted from Horchestra's agentmap.py (https://github.com/SimoneDaniotti/horchestra),
# MIT License, Copyright (c) 2026 Simone Daniotti.
from __future__ import annotations

import re
import time

from .views import STATUS, NodeView, board_text, count_line, mark_line, seat_line

STORY_RE = re.compile(r"\bsc-(\d+)\b")
PR_NUM_RE = re.compile(r"#(\d+)\b")

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


def default_repo(prs):
    """The most common repo among PR refs `owner/repo#n`: its PRs show as `#n`."""
    repos = [p.partition("#")[0] for p in prs]
    return max(sorted(set(repos)), key=repos.count) if repos else None


def pr_label(ref, default=None):
    repo, _, num = ref.partition("#")
    return f"#{num}" if repo == default else ref


def pr_url(ref):
    repo, _, num = ref.partition("#")
    return f"https://github.com/{repo}/pull/{num}" if repo.count("/") == 1 and num.isdigit() else None


def links(t, story_slug=None):
    """[(label, url or None)] for a unit's stories then PRs."""
    out = []
    for story in csv(t.get("stories")):
        out.append((story, story_url(story, story_slug)))
    prs = csv(t.get("prs"))
    default = default_repo(prs)
    for pr in prs:
        out.append((pr_label(pr, default), pr_url(pr)))
    return out


def pr_mark(rec, needs=False, teammate=False):
    """One PR's status mark: ● merged · – closed · ! needs you (an agent on it, or own CI failed) ·
    ✗ changes requested · ◌ draft · ✓ approved · ⟳ in review / CI · · no record."""
    if not isinstance(rec, dict) or not rec.get("state"):
        return "!" if needs else "·"
    if rec["state"] == "merged":
        return "●"
    if rec["state"] == "closed":
        return "–"
    if needs or (rec.get("ci") == "fail" and not teammate):
        return "!"
    if rec.get("decision") == "CHANGES_REQUESTED":
        return "✗"
    if rec.get("draft"):
        return "◌"
    if rec.get("decision") == "APPROVED":
        return "✓"
    return "⟳"


def story_of(text):
    m = STORY_RE.search(text or "")
    return f"sc-{m.group(1)}" if m else None


def stage_map(val):
    out = {}
    for pair in csv(val):
        story, sep, stage = pair.partition("=")
        if sep and story.strip():
            out[story.strip()] = stage.strip()
    return out


def touches(pane, prs, pr_stories, recs):
    """([stories], [PR refs]) an agent touches: its item / pr tokens (csv), story and PR refs in its status
    line, the stories of those PRs and the PRs of those stories. The first of each is what it works on now:
    item before pr before status line; a story's open PRs before its merged / closed ones."""
    t = tokens(pane)
    text = t.get("status") or ""
    stories, refs = [], []

    def add(seq, val):
        if val and val not in seq:
            seq.append(val)

    def resolve(ref):
        num = ref.rpartition("#")[2]
        return ref if ref in prs or not num.isdigit() else next((r for r in prs if r.endswith("#" + num)), ref)

    for item in csv(t.get("item")):
        add(stories, story_of(item))
    for ref in csv(t.get("pr")):
        add(refs, resolve(ref))
    for ref in list(refs):
        for s in pr_stories.get(ref) or []:
            add(stories, s)
    for m in STORY_RE.finditer(text):
        add(stories, f"sc-{m.group(1)}")
    for m in PR_NUM_RE.finditer(text):
        ref = next((r for r in prs if r.endswith("#" + m.group(1))), None)
        add(refs, ref)
        for s in pr_stories.get(ref) or []:
            add(stories, s)
    mine = [r for r in prs if any(s in pr_stories.get(r, []) for s in stories)]
    for r in sorted(mine, key=lambda r: (recs.get(r) or {}).get("state") in ("merged", "closed")):
        add(refs, r)
    return stories, refs


def story_url(story, story_slug):
    num = story.split("-", 1)[-1]
    return f"https://app.shortcut.com/{story_slug}/story/{num}" if story_slug and num.isdigit() else None


def _dict(val):
    return val if isinstance(val, dict) else {}


def build(snap, state=None, own_pane="", here_tab="", now=None, own_workspace="", story_slug=None, operator=None):
    """Snapshot + dispatcher state → Tree. `operator` is the operator's GitHub login: another author's PR
    is a teammate's and shows `@author`."""
    now = time.time() if now is None else now
    state = state if isinstance(state, dict) else {}
    outbox = _dict(state.get("outbox"))
    last_change = _dict(state.get("last_change"))
    cursors = _dict(state.get("cursors"))
    story_epic = _dict(state.get("story_epic"))
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
        node.lead = tree.nodes[pm["pane_id"]] if pm else None
        epic_unit(tree, key, node, t, mine, pm, cursors, story_epic, operator, story_slug)
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


def epic_unit(tree, key, node, t, mine, pm, cursors, story_epic, operator, story_slug=None):
    """A unit's stories, PRs with status marks, agent rows (story · PR now) and, for an epic, its board:
    every story with its stage and PRs, and every agent but the PM with all the stories and PRs it touches."""
    prs = csv(t.get("prs"))
    default = default_repo(prs)
    recs = {r: _dict(cursors.get("pr:" + r)) for r in prs}
    pr_stories = {r: [s for s in recs[r].get("stories") or [] if isinstance(s, str)] for r in prs}
    stories = csv(t.get("stories"))
    stages = stage_map(t.get("stages"))
    node.unit_kind = t.get("kind") or ""
    named = next((_dict(story_epic.get(s)) for s in stories if _dict(story_epic.get(s)).get("name")), {})
    node.ident = str(t.get("epic") or named.get("id") or "")
    if node.unit_kind == "epic":
        node.name = named.get("name") or t.get("unit")

    ties = {p["pane_id"]: touches(p, prs, pr_stories, recs) for p in mine}

    def now(p):
        s, r = ties[p["pane_id"]]
        return (s[0] if s else None), (r[0] if r else None)

    order = list(stories) + [s for s in stages if s not in stories]
    for p in mine:
        s = now(p)[0]
        if s and s not in order and tokens(p).get("role") not in ("pm", "planner"):
            order.append(s)
    unplaced = []
    for r in prs:
        known = [s for s in pr_stories[r] if s in order]
        if not known and pr_stories[r]:
            order.append(pr_stories[r][0])
        elif not pr_stories[r]:
            unplaced.append(r)
    node.stories = order

    needs_on = {}
    for p in mine:
        pr = now(p)[1]
        if pr:
            needs_on[pr] = needs_on.get(pr, False) or tree.nodes[p["pane_id"]].needs
    records = {}
    for r in prs:
        author = recs[r].get("author") or ""
        teammate = bool(author) and author != operator
        records[r] = {"ref": r, "label": pr_label(r, default), "url": pr_url(r), "author": author if teammate else "",
                      "mark": pr_mark(recs[r], needs_on.get(r, False), teammate), "stories": pr_stories[r]}
    node.prs = [records[r] for r in prs]

    rank = {s: i for i, s in enumerate(order)}
    lead = [p for p in mine if p is pm]
    rest = sorted((p for p in mine if p is not pm), key=lambda p: rank.get(now(p)[0], len(rank)))
    node.rows = []
    for p in lead + rest:
        s, r = now(p)
        node.rows.append((tree.nodes[p["pane_id"]], s, pr_label(r, default) if r else None))

    if node.unit_kind != "epic":
        return
    wid = key.split(":", 1)[1]
    node.board = [{"key": f"story:{wid}:{s}", "story": s, "stage": stages.get(s) or "?",
                   "url": story_url(s, story_slug), "prs": [records[r] for r in prs if s in pr_stories[r]]}
                  for s in order]
    if unplaced:
        node.board.append({"key": f"story:{wid}:-", "story": None, "stage": "", "url": None,
                           "prs": [records[r] for r in unplaced]})
    node.crew = []
    for p in rest:
        s, r = ties[p["pane_id"]]
        node.crew.append((tree.nodes[p["pane_id"]], s,
                          [records.get(ref) or {"ref": ref, "label": pr_label(ref, default), "url": pr_url(ref),
                                                "author": "", "mark": "·", "stories": []} for ref in r]))


def crew_of(node, story):
    """Keys of the agents on an epic's board that touch `story`."""
    return [a.key for a, stories, _ in node.crew if story in stories]


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
        if tree.nodes[top].unit_kind == "epic":
            return hub, [a for a, _, _ in tree.nodes[top].crew]
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


def row_text(a, story, pr):
    """One agent row of a unit's agent list: name, status, the story and PR it works on now, status line."""
    bits = [f"{STATUS[a.status][0]} {a.name}"]
    bits += [v for v in (story, pr) if v]
    text = "  ".join(bits)
    return text + (f" — {a.detail}" if a.detail else "")


def to_text(tree):
    """Every level as plain indented text (for --dump and tests)."""
    lines = [header_text(tree)]

    def row(node, lead):
        glyph, word = STATUS[node.status]
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

    def unit_line(node, lead):
        lines.append(lead + "".join(seg[0] for seg in seat_line(node)))
        pad = "│    " if lead.startswith("├") else "     "
        for a, story, pr in node.rows:
            lines.append(f"{pad}{row_text(a, story, pr)}")
        if node.links:
            lines.append(f"{pad}↗ " + "  ".join(label for label, _ in node.links))

    def block(hub, spokes, title=None, each=row):
        if title:
            lines.append("")
            lines.append(title)
        row(hub, "")
        for i, s in enumerate(spokes):
            each(s, "└─ " if i == len(spokes) - 1 else "├─ ")

    block(*level(tree, []), each=unit_line)
    hub, spokes = level(tree, [CONTROL])
    if spokes:
        block(hub, spokes, "[control]")
    for u in tree.units:
        node = tree.nodes[u]
        if node.unit_kind != "epic":
            block(*level(tree, [u]), f"[{node.name}]")
            continue
        hub, _ = level(tree, [u])
        lines.append("")
        lines.append(f"[{node.name}]")
        row(hub, "")
        stage = tokens(tree.raw[u]).get("stage")
        lines.append("   epic " + " · ".join(v for v in (node.name, node.ident) if v) + (f" — {stage}" if stage else ""))
        if node.prs:
            lines.append("   PRs " + mark_line(node.prs))
        lines += ["   " + line for line in board_text(node)]
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
