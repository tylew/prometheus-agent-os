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
        self.assertIn("◼ sc-1-a  (story · implement)  ●2 ○1  !1  ✉2  5m ago", text)
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
