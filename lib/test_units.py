import json
import os
import sys
import tempfile
import unittest

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import units  # noqa: E402


class UnitsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.world_path = os.path.join(self.tmp.name, "world.json")
        os.environ.update(HERDR_BIN=os.path.join(LIB, "testing", "fake_herdr.py"),
                          FAKE_HERDR_WORLD=self.world_path, PROMETHEUS_STATE_DIR=self.tmp.name)
        self.brief = os.path.join(self.tmp.name, "brief.md")
        open(self.brief, "w").write("brief")

    def tearDown(self):
        self.tmp.cleanup()
        for k in ("HERDR_BIN", "FAKE_HERDR_WORLD", "PROMETHEUS_STATE_DIR"):
            os.environ.pop(k, None)

    def world(self):
        return json.load(open(self.world_path))

    def test_create_tags_unit_and_lead_and_launches(self):
        out = units.create("sc-1-a", "story", "besstie", ["sc-1"], ["o/r#10"])
        w = self.world()
        ws = w["workspaces"][0]
        self.assertEqual(ws["tokens"], {"unit": "sc-1-a", "kind": "story", "project": "besstie",
                                        "stories": "sc-1", "prs": "o/r#10", "stage": "triage"})
        pane = w["panes"][0]
        self.assertEqual(pane["tokens"], {"role": "pm"})
        self.assertIn("launch.sh pm", pane["ran"])
        self.assertEqual(w["tabs"][0]["label"], "pm")
        self.assertEqual(out["lead"], "pm")

    def test_planning_unit_leads_with_planner(self):
        units.create("plan-x", "planning", "besstie", [], [])
        w = self.world()
        self.assertEqual(w["panes"][0]["tokens"]["role"], "planner")
        self.assertEqual(w["workspaces"][0]["tokens"]["stage"], "planning")
        self.assertNotIn("stories", w["workspaces"][0]["tokens"])

    def test_duplicate_unit_and_bad_kind_refused(self):
        units.create("sc-1-a", "story", "besstie", ["sc-1"], [])
        with self.assertRaises(ValueError):
            units.create("sc-1-a", "story", "besstie", ["sc-1"], [])
        with self.assertRaises(ValueError):
            units.create("x", "epic", "besstie", [], [])

    def test_open_tab_tags_role_and_passes_allow_extras(self):
        ws = units.create("sc-1-a", "story", "besstie", ["sc-1"], [])["workspace"]
        pane = units.open_tab(ws, "impl-derate", "implementor", item="derate", worktree="/w/derate",
                              extra_allow=["Bash(make lint *)"])
        p = next(x for x in self.world()["panes"] if x["pane_id"] == pane)
        self.assertEqual(p["tokens"], {"role": "implementor", "item": "derate", "worktree": "/w/derate"})
        self.assertIn("PROMETHEUS_EXTRA_ALLOW=", p["ran"])
        self.assertIn("launch.sh implementor", p["ran"])

    def test_send_brief_waits_for_prompt_then_confirms_landing(self):
        ws = units.create("sc-1-a", "story", "besstie", ["sc-1"], [])["workspace"]
        pane = units.open_tab(ws, "review-10", "reviewer", pr="o/r#10")
        self.assertEqual(units.send_brief(pane, self.brief), "landed (working)")
        p = next(x for x in self.world()["panes"] if x["pane_id"] == pane)
        self.assertEqual(p["prompts"], ["Read your brief at %s and begin." % self.brief])

    def test_close_refuses_busy_and_untagged(self):
        ws = units.create("sc-1-a", "story", "besstie", ["sc-1"], [])["workspace"]
        units.open_tab(ws, "impl-a", "implementor")
        w = self.world()
        w["panes"][-1]["agent_status"] = "working"
        json.dump(w, open(self.world_path, "w"))
        with self.assertRaisesRegex(ValueError, "still working"):
            units.close(ws)
        units.close(ws, force=True)
        self.assertEqual(self.world()["workspaces"], [])
        with self.assertRaisesRegex(ValueError, "no prometheus unit"):
            units.close("wNope")

    def test_compact_only_at_prompt(self):
        ws = units.create("sc-1-a", "story", "besstie", ["sc-1"], [])["workspace"]
        pane = units.open_tab(ws, "impl-a", "implementor")
        units.compact(pane, "keep item a")
        with self.assertRaisesRegex(ValueError, "only at its prompt"):
            units.compact(pane, "again")
        p = next(x for x in self.world()["panes"] if x["pane_id"] == pane)
        self.assertEqual(p["prompts"], ["/compact keep item a"])


if __name__ == "__main__":
    unittest.main()
