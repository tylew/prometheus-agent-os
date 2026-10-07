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


def keys(node):
    return [c.key for c in node.children]


class ModelTest(unittest.TestCase):
    def build(self, **kw):
        return model.build(snap(), STATE, now=1300, **kw)

    def test_root_layout(self):
        t = self.build()
        self.assertEqual(len(t.roots), 1)
        root = t.roots[0]
        self.assertEqual(root.name, "prometheus")
        self.assertEqual(keys(root), ["proposals", "wC:p1", "dispatcher", "wC:p2", "unit:wB", "unit:wA",
                                      "unassigned"])
        self.assertEqual(root.status, "working")

    def test_dispatcher_running_and_stopped(self):
        t = self.build()
        d = t.nodes["dispatcher"]
        self.assertEqual(d.status, "running")
        self.assertIn("1 proposal", d.detail)
        self.assertIn("2 held", d.detail)
        s = snap()
        s["workspaces"][0]["tokens"] = {}
        self.assertEqual(model.build(s, {}).nodes["dispatcher"].status, "stopped")

    def test_unit_pm_and_children(self):
        t = self.build()
        unit = t.nodes["unit:wA"]
        self.assertEqual(unit.name, "sc-1-a · story · implement")
        self.assertEqual(unit.detail, "o/r#10, o/r#11 / sc-1 · 5m ago")
        self.assertEqual(keys(unit), ["wA:p1"])
        pm = t.nodes["wA:p1"]
        self.assertEqual(keys(pm), ["wA:p2", "wA:p3"])
        self.assertEqual(t.nodes["wA:p2"].name, "impl sc-1")  # tab label
        self.assertEqual(t.nodes["wA:p3"].name, "reviewer-sc-1")  # numeric tab label falls back

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

    def test_needs_bubbles_to_unit_and_root(self):
        t = self.build()
        self.assertEqual(t.nodes["wA:p1"].flag, 1)
        self.assertEqual(t.nodes["unit:wA"].flag, 1)
        self.assertEqual(t.nodes["unit:wB"].flag, 1)
        self.assertEqual(t.nodes["root"].flag, 3)  # two agents + one proposal

    def test_overlay_held_and_proposals(self):
        t = self.build()
        self.assertEqual(t.nodes["wA:p1"].held, 2)
        self.assertEqual(t.held, 2)
        group = t.nodes["proposals"]
        self.assertTrue(group.needs)
        self.assertEqual(keys(group), ["proposal:p1"])
        self.assertEqual(t.nodes["proposal:p1"].name, "p1 sc-3-c")
        self.assertIn("o/r#30", t.nodes["proposal:p1"].detail)

    def test_self_and_view_exclusion(self):
        t = self.build(own_pane="wC:p2")
        self.assertNotIn("wC:p2", t.nodes)
        self.assertNotIn("wC:p3", t.nodes)  # view=map

    def test_unassigned_and_untagged(self):
        t = self.build()
        self.assertEqual(keys(t.nodes["unassigned"]), ["wX:p9", "wX:p1"])
        self.assertNotIn("wX:p2", t.nodes)  # no role, no unit workspace

    def test_unit_scope(self):
        t = self.build(unit="wA")
        self.assertEqual([r.key for r in t.roots], ["unit:wA"])
        self.assertNotIn("dispatcher", t.nodes)
        self.assertEqual(model.build(snap(), STATE, unit="nope").roots, [])

    def test_empty_inputs(self):
        t = model.build({}, None)
        self.assertEqual(keys(t.roots[0]), ["dispatcher"])
        self.assertEqual(t.dispatcher, "stopped")

    def test_seat_workspace_is_control_without_token(self):
        s = snap()
        s["workspaces"][0]["tokens"] = None
        t = model.build(s, {})
        self.assertEqual(t.raw["dispatcher"]["workspace_id"], "wC")

    def test_to_text(self):
        text = model.to_text(self.build().roots)
        self.assertIn("├─ ? proposals (1) [waiting]  ! needs you", text)
        self.assertIn("✉2 held", text)


class ViewsTest(unittest.TestCase):
    def test_every_view_renders(self):
        roots = model.build(snap(), STATE, now=1300).roots
        for render in (views.render_compact, views.render_cards, views.render_graph):
            canvas, boxes = render(roots, 60)
            self.assertIn("prometheus", canvas.text())
            self.assertIn("unit:wA", boxes)
        canvas, _ = views.render_compact(roots, 80)
        self.assertIn("pm !1 ✉2", canvas.text())
        self.assertIn("!1", canvas.text())

    def test_animate_edges_lights_working(self):
        roots = model.build(snap(), STATE).roots
        canvas, _ = views.render_cards(roots, 50)
        self.assertTrue(views.animate_edges(canvas, {"wA:p3"}, 0))
        self.assertFalse(views.animate_edges(canvas, set(), 0))


if __name__ == "__main__":
    unittest.main()
