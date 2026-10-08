import os
import sys
import unittest

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
from map import model, views  # noqa: E402


def pane(pid, ws, tab, agent_status="idle", agent="claude", **tokens):
    return {"pane_id": pid, "workspace_id": ws, "tab_id": tab, "agent": agent, "agent_status": agent_status,
            "terminal_title_stripped": "title " + pid, "tokens": tokens or None}


def snap():
    return {
        "workspaces": [
            {"workspace_id": "wC", "label": "control", "agent_status": "working",
             "tokens": {"dispatcher": "running"}},
            {"workspace_id": "wA", "label": "a", "agent_status": "working",
             "tokens": {"unit": "sc-1-a", "kind": "story", "project": "besstie", "stories": "sc-1",
                        "prs": "o/r#10,o/r#11", "stage": "implement"}},
            {"workspace_id": "wB", "label": "b", "agent_status": "idle",
             "tokens": {"unit": "rev-b", "kind": "review", "prs": "o/r#20"}},
            {"workspace_id": "wX", "label": "scratch", "agent_status": "idle"},
        ],
        "tabs": [
            {"tab_id": "wA:t2", "workspace_id": "wA", "label": "impl sc-1"},
            {"tab_id": "wA:t3", "workspace_id": "wA", "label": "3"},
        ],
        "panes": [
            pane("wC:p1", "wC", "wC:t1", "working", role="seat"),
            pane("wC:p2", "wC", "wC:t2", role="librarian"),
            pane("wC:p3", "wC", "wC:t1", agent=None, view="map"),
            pane("wA:p1", "wA", "wA:t1", "working", role="pm", status="waiting on CI"),
            pane("wA:p2", "wA", "wA:t2", "idle", role="implementor", item="sc-1", needs="1"),
            pane("wA:p3", "wA", "wA:t3", "working", role="reviewer", item="sc-1", pr="o/r#10", needs="1"),
            pane("wB:p1", "wB", "wB:t1", "blocked", role="pm"),
            pane("wX:p1", "wX", "wX:t1", role="implementor", item="sc-9"),
            pane("wX:p2", "wX", "wX:t1"),
            pane("wX:p9", "wX", "wX:t1", role="pm"),
        ],
    }


STATE = {
    "outbox": {"wA:p1": [{"line": "PR 10 approved", "details": {}, "ts": 1}, {"line": "CI red", "ts": 2}]},
    "proposals": [{"id": "o/r#30", "pid": "p1", "kind": "story", "name": "sc-3-c", "project": "besstie",
                   "stories": ["sc-3"], "prs": ["o/r#30"], "reason": "new PR", "event": "PR 30 opened"}],
    "last_change": {"sc-1-a": 1000},
}


def epic_snap():
    """Two epic units and one older review unit."""
    return {
        "workspaces": [
            {"workspace_id": "wC", "label": "control", "tokens": {"dispatcher": "running"}},
            {"workspace_id": "wE", "label": "grid", "tokens": {
                "unit": "epic-77-grid", "kind": "epic", "epic": "77", "project": "besstie",
                "stories": "sc-1,sc-2,sc-3", "prs": "o/r#10,o/r#11,o/r#12,x/y#5",
                "stage": "sc-1 implement, sc-2 in review", "stages": "sc-1=implement,sc-2=review"}},
            {"workspace_id": "wF", "label": "billing", "tokens": {
                "unit": "epic-88-billing", "kind": "epic", "epic": "88", "project": "besstie",
                "stories": "sc-5", "prs": "o/r#20,o/r#21"}},
            {"workspace_id": "wB", "label": "b", "tokens": {"unit": "rev-b", "kind": "review", "prs": "o/r#30"}},
        ],
        "tabs": [{"tab_id": "wE:t2", "workspace_id": "wE", "label": "impl sc-1"},
                 {"tab_id": "wE:t3", "workspace_id": "wE", "label": "review #12"}],
        "panes": [
            pane("wC:p1", "wC", "wC:t1", "idle", role="seat"),
            pane("wE:p1", "wE", "wE:t1", "working", role="pm", status="sc-2 in review"),
            pane("wE:p2", "wE", "wE:t2", "idle", role="implementor", item="sc-1", status="fixing #11", needs="1"),
            pane("wE:p3", "wE", "wE:t3", "working", role="reviewer", pr="o/r#12", status="round 2"),
            pane("wE:p4", "wE", "wE:t4", "idle", role="planner", item="epic-77", status="planning sc-3"),
            pane("wF:p1", "wF", "wF:t1", "idle", role="pm"),
            pane("wF:p2", "wF", "wF:t2", "working", role="implementor", item="sc-5-fix", status="tests"),
            pane("wB:p1", "wB", "wB:t1", "idle", role="pm", status="review r1"),
        ],
    }


def pr_rec(state="open", draft=False, ci="pass", decision="", stories=(), author="tylew"):
    return {"state": state, "draft": draft, "ci": ci, "decision": decision, "review": "",
            "stories": list(stories), "author": author}


EPIC_STATE = {
    "cursors": {
        "pr:o/r#10": pr_rec(decision="APPROVED", stories=["sc-1"]),
        "pr:o/r#11": pr_rec(draft=True, ci="pending", stories=["sc-1"]),
        "pr:o/r#12": pr_rec(decision="REVIEW_REQUIRED", stories=["sc-2"], author="alice"),
        "pr:x/y#5": pr_rec(state="merged", stories=["sc-2"]),
        "pr:o/r#20": pr_rec(decision="CHANGES_REQUESTED", stories=["sc-5"], author="bob", ci="fail"),
        "pr:o/r#21": pr_rec(ci="fail", stories=["sc-5"]),
        "pr:o/r#30": pr_rec(decision="APPROVED", author="carol"),
    },
    "story_epic": {"sc-1": {"id": 77, "name": "Grid programs"}, "sc-5": {"id": 88, "name": "Billing"}},
}


def keys(nodes):
    return [n.key for n in nodes]


class ModelTest(unittest.TestCase):
    def build(self, **kw):
        return model.build(snap(), STATE, now=1300, **kw)

    def test_system_level_is_seat_over_units(self):
        t = self.build()
        hub, spokes = model.level(t, [])
        self.assertEqual(hub.key, "wC:p1")
        self.assertEqual(hub.kind, "seat")
        self.assertEqual(keys(spokes), ["unit:wB", "unit:wA"])
        self.assertNotIn("root", t.nodes)
        self.assertNotIn("dispatcher", t.nodes)

    def test_unit_stats(self):
        unit = self.build().nodes["unit:wA"]
        self.assertEqual(unit.name, "sc-1-a")
        self.assertEqual(unit.sub, "story · implement")
        self.assertEqual(unit.counts, {"working": 2, "idle": 1})
        self.assertEqual(unit.flag, 1)
        self.assertEqual(unit.held, 2)
        self.assertEqual(unit.age, "5m")
        self.assertEqual(unit.status, "working")
        self.assertEqual(self.build().nodes["unit:wB"].status, "blocked")

    def test_unit_level_is_pm_over_workers(self):
        t = self.build()
        hub, spokes = model.level(t, ["unit:wA"])
        self.assertEqual(hub.key, "wA:p1")
        self.assertEqual(keys(spokes), ["wA:p2", "wA:p3"])
        self.assertEqual(t.nodes["wA:p2"].name, "impl sc-1")  # tab label
        self.assertEqual(t.nodes["wA:p3"].name, "reviewer-sc-1")  # numeric tab label falls back

    def test_unit_without_pm_is_its_own_hub(self):
        s = snap()
        s["panes"] = [p for p in s["panes"] if p["pane_id"] != "wB:p1"]
        t = model.build(s, STATE)
        hub, spokes = model.level(t, ["unit:wB"])
        self.assertEqual(hub.key, "unit:wB")
        self.assertEqual(spokes, [])
        self.assertIsNone(model.preview_target(t, "unit:wB"))

    def test_control_level(self):
        t = self.build()
        hub, spokes = model.level(t, [model.CONTROL])
        self.assertEqual(hub.key, "wC:p1")
        self.assertEqual(keys(spokes), ["wC:p2", "wX:p9", "wX:p1", "proposal:p1"])
        self.assertEqual(hub.flag, 1)  # the proposal

    def test_quick_runners_on_the_control_level(self):
        s = snap()
        s["tabs"].append({"tab_id": "wC:t5", "workspace_id": "wC", "label": "quick-battery-curves"})
        s["panes"].append(pane("wC:p5", "wC", "wC:t5", "working", role="runner", item="battery-curves"))
        t = model.build(s, STATE, now=1300)
        self.assertIn("wC:p5", t.control)
        self.assertEqual(t.nodes["wC:p5"].name, "quick-battery-curves")

    def test_another_instances_control_roles_are_left_out(self):
        s = snap()
        s["workspaces"].append({"workspace_id": "wT", "label": "trial", "tokens": {}})
        s["panes"] += [pane("wT:p1", "wT", "wT:t1", role="seat"), pane("wT:p2", "wT", "wT:t2", role="librarian")]
        t = model.build(s, STATE, now=1300, own_workspace="wC")
        self.assertNotIn("wT:p1", t.nodes)
        self.assertNotIn("wT:p2", t.nodes)
        self.assertEqual(t.seat, "wC:p1")

    def test_header_stats(self):
        t = self.build()
        self.assertEqual(t.dispatcher, "running")
        self.assertEqual(t.held, 2)
        self.assertEqual(t.needs, 2)
        self.assertEqual(model.header_text(t), "dispatcher running · 8 agents · ●3 ▲1 ○4 · !2 · ?1 · ✉2")
        s = snap()
        s["workspaces"][0]["tokens"] = {}
        self.assertEqual(model.build(s, {}).dispatcher, "stopped")

    def test_detail_line_precedence(self):
        t = self.build()
        self.assertEqual(t.nodes["wA:p1"].detail, "waiting on CI")
        self.assertEqual(t.nodes["wA:p2"].detail, "needs you")
        self.assertEqual(t.nodes["wA:p3"].detail, "sc-1 · o/r#10")
        self.assertEqual(t.nodes["wC:p2"].detail, "title wC:p2")

    def test_needs_you(self):
        t = self.build()
        self.assertTrue(t.nodes["wA:p2"].needs)
        self.assertFalse(t.nodes["wA:p3"].needs)  # needs=1 but working
        self.assertTrue(t.nodes["wB:p1"].needs)  # blocked

    def test_preview_targets_and_drilling(self):
        t = self.build()
        self.assertEqual(model.preview_target(t, "unit:wA"), "wA:p1")
        self.assertEqual(model.preview_target(t, "wA:p3"), "wA:p3")
        self.assertEqual(model.preview_target(t, "wC:p1"), "wC:p1")
        self.assertIsNone(model.preview_target(t, "proposal:p1"))
        self.assertEqual(model.drill_path(t, "unit:wA"), "unit:wA")
        self.assertEqual(model.drill_path(t, "wC:p1"), model.CONTROL)
        self.assertIsNone(model.drill_path(t, "wA:p3"))
        self.assertEqual(model.unit_of(t, "wA:p3"), "unit:wA")

    def test_self_and_view_exclusion(self):
        t = self.build(own_pane="wC:p2")
        self.assertNotIn("wC:p2", t.nodes)
        self.assertNotIn("wC:p3", t.nodes)  # view=map
        self.assertNotIn("wX:p2", t.nodes)  # no role, no unit workspace

    def test_empty_inputs(self):
        t = model.build({}, None)
        hub, spokes = model.level(t, [])
        self.assertEqual(hub.name, "no seat")
        self.assertEqual(spokes, [])
        self.assertEqual(t.dispatcher, "stopped")

    def test_to_text(self):
        text = model.to_text(self.build())
        self.assertTrue(text.startswith("dispatcher running"))
        self.assertIn("└─ ◼ sc-1-a · story  ● pm  1 sc  ⚑1  ✉2  5m", text)
        self.assertIn("     ● reviewer-sc-1  sc-1  #10 — sc-1 · o/r#10", text)
        self.assertIn("[sc-1-a]", text)
        self.assertIn("[control]", text)


class ViewsTest(unittest.TestCase):
    def render(self, path, width, **kw):
        t = model.build(snap(), STATE, now=1300)
        hub, spokes = model.level(t, path)
        return views.render_level(hub, spokes, width, **kw), hub, spokes

    def assert_fits(self, canvas, width):
        for row in canvas.text().splitlines():
            self.assertLessEqual(len(row), width)

    def test_system_level_single_row(self):
        (canvas, boxes), hub, spokes = self.render([], 100, spark={"unit:wA": "▁▃█"})
        text = canvas.text()
        self.assert_fits(canvas, 100)
        self.assertIn("┏", text)  # seat box
        self.assertIn("╔", text)  # unit boxes
        self.assertIn("◼ sc-1-a", text)
        self.assertIn("story · implement  !1 ✉2 5m", text)
        self.assertIn("✻ ● pm ✉2  waiting on CI", text)
        self.assertIn("✻ ○ impl sc-1  ! needs you", text)
        self.assertIn("▁▃█", text)
        self.assertIn("1 sc-1  2 #10  3 #11", text)
        self.assertLess(boxes["wC:p1"][1], boxes["unit:wA"][0])
        self.assertEqual(boxes["unit:wA"][0], boxes["unit:wB"][0])

    def test_links_are_recorded_for_clicks(self):
        t = model.build(snap(), STATE, now=1300, story_slug="acme")
        self.assertEqual(t.nodes["unit:wA"].links, [
            ("sc-1", "https://app.shortcut.com/acme/story/1"),
            ("#10", "https://github.com/o/r/pull/10"), ("#11", "https://github.com/o/r/pull/11")])
        hub, spokes = model.level(t, [])
        canvas, _ = views.render_level(hub, spokes, 100)
        urls = [u for _, _, _, u in canvas.links]
        self.assertIn("https://github.com/o/r/pull/11", urls)
        y, x0, x1, _ = canvas.links[urls.index("https://app.shortcut.com/acme/story/1")]
        self.assertEqual(canvas.text().splitlines()[y][x0:x1 + 1], "sc-1")

    def test_long_link_lists_wrap(self):
        t = model.build(snap(), STATE, now=1300, story_slug="acme")
        t.nodes["unit:wA"].links = [(f"sc-10000{i}", f"https://x/{i}") for i in range(6)]
        canvas, _ = views.render_level(*model.level(t, []), 90)
        text = canvas.text()
        for i in range(6):
            self.assertIn(f"{i + 1} sc-10000{i}", text)
        self.assertEqual(len(canvas.links), 7)  # six here plus rev-b's PR
        self.assertNotIn("no agents", text)

    def test_hidden_agents_fold_to_counts(self):
        t = model.build(snap(), STATE, now=1300)
        unit = t.nodes["unit:wA"]
        unit.agents = unit.agents * 2
        canvas, _ = views.render_level(*model.level(t, []), 100)
        self.assertIn("+1 more", canvas.text())
        self.assertIn("●2 ○1", canvas.text())

    def test_font_icons(self):
        views.use_font(True)
        try:
            canvas, _ = views.render_level(*model.level(model.build(snap(), STATE), ["unit:wA"]), 80)
            self.assertIn("\ue1a0 \ue1c2 reviewer-sc-1", canvas.text())
        finally:
            views.use_font(False)

    def test_wraps_into_rows(self):
        t = model.build(snap(), STATE)
        hub, _ = model.level(t, [])
        spokes = [views.NodeView(f"k{i}", f"agent-{i}", "claude", "idle") for i in range(7)]
        canvas, boxes = views.render_level(hub, spokes, 60)
        self.assert_fits(canvas, 60)
        tops = sorted({boxes[f"k{i}"][0] for i in range(7)})
        self.assertEqual(len(tops), 4)  # 2 per row at 60 columns
        self.assertEqual(len(canvas.edges), 7)

    def test_unit_level_and_narrow(self):
        (canvas, boxes), hub, spokes = self.render(["unit:wA"], 40)
        self.assert_fits(canvas, 40)
        self.assertIn("! needs you", canvas.text())
        self.assertIn("wA:p3", boxes)

    def test_animate_edges_lights_working(self):
        (canvas, _), _, _ = self.render(["unit:wA"], 80)
        self.assertTrue(views.animate_edges(canvas, {"wA:p3"}, 0))
        self.assertFalse(views.animate_edges(canvas, set(), 0))


class EpicTest(unittest.TestCase):
    def build(self):
        return model.build(epic_snap(), EPIC_STATE, operator="tylew", story_slug="acme")

    def line(self, t, key):
        return "".join(seg[0] for seg in views.seat_line(t.nodes[key]))

    def test_seat_level_compact_lines(self):
        t = self.build()
        hub, spokes = model.level(t, [])
        self.assertEqual(keys(spokes), ["unit:wE", "unit:wF", "unit:wB"])
        self.assertEqual(self.line(t, "unit:wE"), "◼ Grid programs · 77  ● pm  3 sc · ✓1 ⟳1 ●1 !1  ⚑1")
        self.assertEqual(self.line(t, "unit:wF"), "◼ Billing · 88  ○ pm  1 sc · ✗1 !1")
        self.assertEqual(self.line(t, "unit:wB"), "◼ rev-b · review  ○ pm  0 sc · ✓1")
        canvas, boxes = views.render_seat(hub, spokes, 90)
        text = canvas.text()
        self.assertIn("├─  ◼ Grid programs · 77", text)
        self.assertIn("└─  ◼ rev-b · review", text)
        self.assertNotIn("@", text)
        self.assertNotIn("╔", text)
        self.assertEqual(boxes["unit:wE"][0], boxes["unit:wE"][1])  # one line
        self.assertEqual(boxes["unit:wF"][0] + 1, boxes["unit:wB"][0])
        self.assertEqual(len(canvas.edges), 3)
        spokes[0].selected = True
        self.assertIn("├─▸ ◼ Grid programs", views.render_seat(hub, spokes, 90)[0].text())

    def test_teammate_ci_failure_is_not_needs_you(self):
        t = self.build()
        marks = {p["label"]: (p["mark"], p["author"]) for p in t.nodes["unit:wF"].prs}
        self.assertEqual(marks, {"#20": ("✗", "bob"), "#21": ("!", "")})
        # no operator configured: every author shows
        t = model.build(epic_snap(), EPIC_STATE)
        self.assertEqual(t.nodes["unit:wE"].prs[0]["author"], "tylew")

    def test_preview_agent_rows(self):
        t = self.build()
        rows = [(a.key, story, pr) for a, story, pr in t.nodes["unit:wE"].rows]
        self.assertEqual(rows, [("wE:p1", "sc-2", "#12"), ("wE:p2", "sc-1", "#11"), ("wE:p3", "sc-2", "#12"),
                                ("wE:p4", "sc-3", None)])
        self.assertEqual(model.row_text(*t.nodes["unit:wE"].rows[2]), "● review #12  sc-2  #12 — round 2")
        rows = [(a.key, story, pr) for a, story, pr in t.nodes["unit:wF"].rows]
        self.assertEqual(rows, [("wF:p1", None, None), ("wF:p2", "sc-5", "#20")])

    def test_epic_level_is_a_board(self):
        t = self.build()
        node = t.nodes["unit:wE"]
        self.assertEqual([(r["story"], r["stage"]) for r in node.board],
                         [("sc-1", "implement"), ("sc-2", "review"), ("sc-3", "?")])
        self.assertEqual([(p["label"], p["mark"]) for p in node.board[0]["prs"]], [("#10", "✓"), ("#11", "!")])
        self.assertEqual(node.board[0]["url"], "https://app.shortcut.com/acme/story/1")
        crew = {a.key: (stories, [p["label"] for p in prs]) for a, stories, prs in node.crew}
        self.assertEqual(crew, {"wE:p2": (["sc-1"], ["#11", "#10"]), "wE:p3": (["sc-2"], ["#12", "x/y#5"]),
                                "wE:p4": (["sc-3"], [])})
        hub, spokes = model.level(t, ["unit:wE"])
        self.assertEqual(hub.key, "wE:p1")
        self.assertEqual(keys(spokes), ["wE:p2", "wE:p3", "wE:p4"])  # planner included, PM not
        self.assertEqual(node.name, "Grid programs")
        self.assertEqual(t.nodes["unit:wB"].board, [])  # an older unit keeps its PM-over-agents level
        hub, spokes = model.level(t, ["unit:wB"])
        self.assertEqual((hub.key, spokes), ("wB:p1", []))

    def test_multi_tie_spans_a_stack(self):
        s = epic_snap()
        s["panes"].append(pane("wE:p5", "wE", "wE:t5", "working", role="reviewer", pr="o/r#10, #12",
                               status="r2 on #12"))
        t = model.build(s, EPIC_STATE, operator="tylew")
        crew = {a.key: (stories, [p["label"] for p in prs]) for a, stories, prs in t.nodes["unit:wE"].crew}
        self.assertEqual(crew["wE:p5"], (["sc-1", "sc-2"], ["#10", "#12", "#11", "x/y#5"]))
        self.assertEqual(model.crew_of(t.nodes["unit:wE"], "sc-1"), ["wE:p2", "wE:p5"])
        self.assertEqual(model.crew_of(t.nodes["unit:wE"], "sc-2"), ["wE:p5", "wE:p3"])
        row = next(r for r in t.nodes["unit:wE"].rows if r[0].key == "wE:p5")
        self.assertEqual(row[1:], ("sc-1", "#10"))  # the seat list keeps one story / PR: what it works on now
        idle = pane("wE:p6", "wE", "wE:t6", role="implementor")
        self.assertEqual(model.touches(idle, [], {}, {}), ([], []))
        self.assertIn("  (nothing yet)", views.board_text(model.build(
            {**s, "panes": s["panes"] + [idle]}, EPIC_STATE).nodes["unit:wE"]))

    def test_every_story_listed_and_prs_without_one(self):
        s = epic_snap()
        s["workspaces"][1]["tokens"]["stories"] += ",sc-4"
        s["workspaces"][1]["tokens"]["prs"] += ",o/r#13"
        t = model.build(s, EPIC_STATE, operator="tylew")
        node = t.nodes["unit:wE"]
        self.assertEqual([r["story"] for r in node.board], ["sc-1", "sc-2", "sc-3", "sc-4", None])
        self.assertEqual(model.crew_of(node, "sc-4"), [])
        self.assertEqual([p["label"] for p in node.board[-1]["prs"]], ["#13"])
        lines = views.board_text(node)
        self.assertIn("stories (4)", lines)
        self.assertIn("sc-4     ?         —", lines)
        self.assertIn("no story           #13·", lines)

    def board(self, sel, width=120):
        t = self.build()
        hub, _ = model.level(t, ["unit:wE"])
        return views.render_epic(hub, t.nodes["unit:wE"], width, sel=sel, hub_title="Grid programs · 77")

    def style_at(self, canvas, text):
        for y, line in enumerate(canvas.text().splitlines()):
            if text in line:
                return canvas.rows[y][line.index(text)][1]
        raise AssertionError(text)

    def test_cross_highlight(self):
        canvas, boxes = self.board("story:wE:sc-2")
        self.assertEqual(self.style_at(canvas, "review #12"), "hl")
        self.assertEqual(self.style_at(canvas, "impl sc-1"), "name")
        self.assertEqual(self.style_at(canvas, "sc-2 review"), "selname")
        self.assertEqual(views.hot(self.build().nodes["unit:wE"], "story:wE:sc-2"), (set(), set(), {"wE:p3"}))
        canvas, boxes = self.board("wE:p2")
        self.assertEqual(self.style_at(canvas, "sc-1 implement"), "hl")
        self.assertEqual(self.style_at(canvas, "sc-2 review"), "name")
        self.assertEqual(self.style_at(canvas, "#11!"), "hl")
        self.assertEqual(self.style_at(canvas, "impl sc-1"), "selname")
        y0, y1, x0, _ = boxes["wE:p2"]
        self.assertEqual((y1 - y0, canvas.text().splitlines()[y0][x0]), (1, "▸"))

    def test_board_side_by_side_and_stacked(self):
        canvas, boxes = self.board("story:wE:sc-1", 100)
        text = canvas.text()
        self.assertIn("Grid programs · 77", text)
        heads = [y for y, line in enumerate(text.splitlines()) if "stories (3)" in line or "agents (3)" in line]
        self.assertEqual(len(set(heads)), 1)  # one header row: side by side
        self.assertGreater(boxes["wE:p2"][2], boxes["story:wE:sc-1"][3])
        self.assertIn("▸sc-1 implement #10✓ #11!", text)
        self.assertIn("sc-2 review    #12⟳ @alice x/y#5●", text)
        self.assertIn("https://github.com/o/r/pull/12", [u for *_, u in canvas.links])
        for width in (50, 30, 22):
            canvas, boxes = self.board("wE:p3", width)
            for row in canvas.text().splitlines():
                self.assertLessEqual(len(row), width)
            self.assertGreater(boxes["wE:p2"][0], boxes["story:wE:sc-3"][1])  # agents below the stories
            self.assertEqual(boxes["wE:p2"][2], 0)
        self.assertIn("@alice", self.board("wE:p3", 30)[0].text())  # a long PR list wraps, nothing dropped
        self.assertIn("x/y#5●", self.board("wE:p3", 30)[0].text())

    def test_dump_covers_the_new_levels(self):
        text = model.to_text(self.build())
        self.assertIn("├─ ◼ Grid programs · 77  ● pm  3 sc · ✓1 ⟳1 ●1 !1  ⚑1", text)
        self.assertIn("│    ○ impl sc-1  sc-1  #11 — fixing #11", text)
        self.assertIn("│    ↗ sc-1  sc-2  sc-3  #10  #11  #12  x/y#5", text)
        self.assertIn("[Grid programs]", text)
        self.assertIn("   epic Grid programs · 77 — sc-1 implement, sc-2 in review", text)
        self.assertIn("   stories (3)\n   sc-1 implement #10✓ #11!\n   sc-2 review    #12⟳ @alice x/y#5●\n"
                      "   sc-3 ?         —\n   agents (3)\n   impl sc-1 ○  ! fixing #11\n     sc-1 · #11 #10", text)
        self.assertIn("   planner-epic-77 ○  planning sc-3\n     sc-3", text)
        self.assertIn("[rev-b]\n○ pm [idle]  — review r1", text)


class BoardNavTest(unittest.TestCase):
    def app(self):
        from map import app as mapapp
        a = mapapp.App(None, unit="wE")
        a.tree = model.build(epic_snap(), EPIC_STATE, operator="tylew", story_slug="acme")
        a.rebuild()
        return a

    def test_columns_and_enter(self):
        import curses
        from unittest import mock
        from map import app as mapapp
        a = self.app()
        self.assertEqual(a.selected(), "story:wE:sc-1")
        self.assertEqual(a.target(a.selected()), "wE:p2")  # a story previews the first agent touching it
        a.handle(curses.KEY_DOWN)
        self.assertEqual(a.selected(), "story:wE:sc-2")
        a.handle(curses.KEY_RIGHT)
        self.assertEqual(a.selected(), "wE:p3")  # the agent on sc-2
        a.handle(curses.KEY_DOWN)
        self.assertEqual(a.selected(), "wE:p4")
        a.handle(curses.KEY_DOWN)
        self.assertEqual(a.selected(), "wE:p4")  # stays in its column
        a.handle(curses.KEY_LEFT)
        self.assertEqual(a.selected(), "story:wE:sc-3")
        with mock.patch.object(mapapp, "open_url") as opened:
            a.handle("\n")
        opened.assert_called_once_with("https://app.shortcut.com/acme/story/3")
        a.handle("\t")
        a.handle("\r")
        self.assertEqual(a.interact, "wE:p4")
        a.interact = None
        a.select("story:wE:sc-1")
        a.handle(curses.KEY_LEFT)
        self.assertEqual(a.path, [])
        self.assertEqual(a.selected(), "unit:wE")


class IconsTest(unittest.TestCase):
    def test_missing_font_installs_and_stays_on_text(self):
        import tempfile
        from unittest import mock
        from map import icons
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"PROMETHEUS_MAP_ICONS": ""}), \
                mock.patch.object(icons, "FONT_DIRS", (home,)), \
                mock.patch.object(icons, "user_font_dir", lambda: home):
            self.assertFalse(icons.font_wanted())
            self.assertTrue(os.path.isfile(os.path.join(home, "HerdrAgentIconsMax-Regular.ttf")))
            self.assertTrue(icons.font_wanted())

    def test_override(self):
        from unittest import mock
        from map import icons
        with mock.patch.dict(os.environ, {"PROMETHEUS_MAP_ICONS": "text"}):
            self.assertFalse(icons.font_wanted())


class MouseTest(unittest.TestCase):
    def test_sgr_reports(self):
        from map.app import parse_mouse
        self.assertEqual(parse_mouse("[<64;10;5M"), (64, 9, 4, True))  # wheel up
        self.assertEqual(parse_mouse("[<65;1;1M"), (65, 0, 0, True))  # wheel down
        self.assertEqual(parse_mouse("[<0;3;4m"), (0, 2, 3, False))  # release
        self.assertIsNone(parse_mouse("[A"))
        self.assertIsNone(parse_mouse("[<x;1;1M"))


if __name__ == "__main__":
    unittest.main()
