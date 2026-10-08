import json
import os
import sys
import tempfile
import unittest
import unittest.mock

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
        self.assertIn("--agent prometheus:project-manager", pane["ran"])
        self.assertIn("--name pm", pane["ran"])
        self.assertEqual(pane["agent_name"], "sc-1-a-%s" % pane["pane_id"].replace(":", "-").lower())
        long = units.herdr_name("review-43649-let-users-enter-plc-and", "w1F:p1")
        self.assertEqual((long, len(long) <= 32), ("review-43649-let-users-en-w1f-p1", True))
        self.assertTrue(units.herdr_name("9-x", "w1:p2")[0].isalpha())
        self.assertEqual(w["tabs"][0]["label"], "pm")
        self.assertEqual(out["lead"], "pm")

    def test_duplicate_unit_and_bad_kind_refused(self):
        units.create("sc-1-a", "story", "besstie", ["sc-1"], [])
        with self.assertRaises(ValueError):
            units.create("sc-1-a", "story", "besstie", ["sc-1"], [])
        with self.assertRaises(ValueError):
            units.create("x", "epic", "besstie", [], [])
        with self.assertRaises(ValueError):
            units.create("plan-x", "planning", "besstie", [], [])

    def test_tokens_sets_stage_stories_prs_on_the_callers_unit_only(self):
        out = units.create("sc-1-a", "story", "besstie", ["sc-1"], ["o/r#10"])
        got = units.set_tokens(out["workspace"], stage="review", add_prs=["o/r#11", "o/r#10"])
        self.assertEqual((got["stage"], got["prs"]), ("review", "o/r#10,o/r#11"))
        units.set_tokens(out["workspace"], stories="sc-1,sc-2")
        self.assertEqual(self.world()["workspaces"][0]["tokens"],
                         {"unit": "sc-1-a", "kind": "story", "project": "besstie",
                          "stories": "sc-1,sc-2", "prs": "o/r#10,o/r#11", "stage": "review"})
        with self.assertRaises(TypeError):
            units.set_tokens(out["workspace"], unit="x")
        with self.assertRaises(ValueError):
            units.set_tokens(out["workspace"])
        with unittest.mock.patch.dict(os.environ, {"HERDR_PANE_ID": out["pane"]}):
            self.assertEqual(units.main(["tokens", "--stage", "design"]), 0)
        self.assertEqual(self.world()["workspaces"][0]["tokens"]["stage"], "design")
        with unittest.mock.patch.dict(os.environ, {"HERDR_PANE_ID": "w9:p9"}):
            self.assertEqual(units.main(["tokens", "--stage", "design"]), 1)

    def test_open_tab_tags_role_and_passes_allow_extras(self):
        ws = units.create("sc-1-a", "story", "besstie", ["sc-1"], [])["workspace"]
        pane = units.open_tab(ws, "impl-derate", "implementor", item="derate", worktree="/w/derate",
                              extra_allow=["Bash(make lint *)"])
        p = next(x for x in self.world()["panes"] if x["pane_id"] == pane)
        self.assertEqual(p["tokens"], {"role": "implementor", "item": "derate", "worktree": "/w/derate"})
        self.assertIn("--agent prometheus:implementor", p["ran"])
        self.assertIn("--permission-mode dontAsk --name impl-derate", p["ran"])
        settings = json.load(open(os.path.join(self.tmp.name, "settings", "implementor.json")))
        self.assertIn("Bash(make lint *)", settings["permissions"]["allow"])

    def test_send_brief_lands_with_prompt_wait(self):
        ws = units.create("sc-1-a", "story", "besstie", ["sc-1"], [])["workspace"]
        pane = units.open_tab(ws, "review-10", "reviewer", pr="o/r#10")
        self.assertEqual(units.send_brief(pane, self.brief), "landed (started)")
        p = next(x for x in self.world()["panes"] if x["pane_id"] == pane)
        self.assertEqual(p["prompts"], ["Read your brief at %s and begin." % self.brief])

    def test_send_brief_resends_once_after_a_stall(self):
        os.environ["FAKE_HERDR_STALL"] = "1"
        try:
            ws = units.create("sc-1-a", "story", "besstie", ["sc-1"], [])["workspace"]
            pane = units.open_tab(ws, "review-10", "reviewer", pr="o/r#10")
            with unittest.mock.patch("time.sleep"):
                self.assertEqual(units.send_brief(pane, self.brief), "landed (started)")
        finally:
            del os.environ["FAKE_HERDR_STALL"]
        p = next(x for x in self.world()["panes"] if x["pane_id"] == pane)
        self.assertEqual(len(p["prompts"]), 2)

    def test_close_drops_the_restore_image(self):
        import dispatch
        ws = units.create("sc-1-a", "story", "besstie", ["sc-1"], [])["workspace"]
        with dispatch.locked_state() as st:
            dispatch.update_image(dispatch.snapshot(), st)
            self.assertIn("sc-1-a", st["image"])
        units.close(ws, force=True)
        with dispatch.locked_state() as st:
            self.assertNotIn("sc-1-a", st["image"])

    def test_restore_recreates_unit_and_resumes_sessions(self):
        import dispatch
        projects = os.path.join(self.tmp.name, "claude", "projects", "-ws")
        os.makedirs(projects)
        open(os.path.join(projects, "s-pm.jsonl"), "w").close()
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.tmp.name, "claude")
        try:
            with dispatch.locked_state() as st:
                st["image"] = {"sc-1-a": {"tokens": {"unit": "sc-1-a", "kind": "story", "project": "besstie",
                                                     "stories": "sc-1", "stage": "implement"},
                                          "agents": [{"label": "pm", "tokens": {"role": "pm"}, "session": "s-pm"},
                                                     {"label": "impl-a", "tokens": {"role": "implementor", "item": "a"},
                                                      "session": "s-gone"}]}}
                st["restore_backlog"] = {"sc-1-a": ["[prometheus] ci pass o/r#10"]}
            out = units.restore_all()
        finally:
            del os.environ["CLAUDE_CONFIG_DIR"]
        self.assertEqual((out[0]["back"], out[0]["missing"]), (["pm"], ["impl-a"]))
        w = self.world()
        self.assertEqual(w["workspaces"][0]["tokens"]["stage"], "implement")
        pm = w["panes"][0]
        self.assertEqual(pm["tokens"], {"role": "pm"})
        self.assertIn("--resume s-pm", pm["ran"])
        with dispatch.locked_state() as st:
            self.assertEqual(st["outbox"][pm["pane_id"]][0]["line"], "[prometheus] ci pass o/r#10")
            self.assertEqual(dispatch.pending_restore(dispatch.snapshot(), st), {})

    def test_quick_opens_a_runner_tab_with_exports_and_brief(self):
        ws = units.create("sc-1-a", "story", "besstie", ["sc-1"], [])["workspace"]
        out = units.quick(ws, "Battery Curves CSV", "export the battery curves as a single csv")
        self.assertEqual((out["label"], out["brief"]), ("quick-battery-curves-csv", "landed (started)"))
        self.assertTrue(os.path.isdir(out["exports"]))
        p = next(x for x in self.world()["panes"] if x["pane_id"] == out["pane"])
        self.assertEqual(p["tokens"], {"role": "runner", "item": "battery-curves-csv"})
        self.assertIn("--agent prometheus:runner", p["ran"])
        self.assertIn("--name quick-battery-curves-csv", p["ran"])
        self.assertNotIn("dontAsk", p["ran"])
        brief = open(os.path.join(self.tmp.name, "briefs", "quick-battery-curves-csv.md")).read()
        self.assertIn("export the battery curves as a single csv", brief)
        with self.assertRaisesRegex(ValueError, "already open"):
            units.quick(ws, "battery-curves-csv", "again")

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

    def _respawn(self, live_polls):
        def snap(agent):
            pane = {"pane_id": "w1F:p1", "workspace_id": "w1F", "tab_id": "w1F:t1", "tokens": {"role": "pm"},
                    "agent_session": {"value": "s-1"}, "agent_status": "done", "agent": agent}
            return {"panes": [pane], "tabs": [{"tab_id": "w1F:t1", "label": "pm"}], "workspaces": []}
        snaps = iter([snap("claude")] * (1 + live_polls) + [snap(None)] * 10)
        clock = iter(range(0, 1000))
        with unittest.mock.patch.object(units, "_snap", side_effect=lambda: next(snaps)), \
                unittest.mock.patch.object(units.hz, "call") as call, \
                unittest.mock.patch.object(units, "start") as start, \
                unittest.mock.patch.object(units.time, "sleep"), \
                unittest.mock.patch.object(units.time, "time", side_effect=lambda: next(clock)):
            try:
                return units.respawn("w1F:p1", timeout=30), call, start
            except ValueError as exc:
                return exc, call, start

    def test_respawn_repeats_ctrl_c_until_the_agent_exits_then_resumes(self):
        out, call, start = self._respawn(live_polls=6)
        self.assertIn("respawned pm", out)
        self.assertEqual([c.args for c in call.call_args_list], [("agent", "send-keys", "w1F:p1", "ctrl+c", "ctrl+c")] * 2)
        start.assert_called_once()
        self.assertEqual(start.call_args.kwargs["claude_args"],
                         ["--resume", "s-1", "--system-prompt-snapshot", "off"])

    def test_respawn_refuses_to_start_over_an_agent_that_did_not_exit(self):
        out, call, start = self._respawn(live_polls=999)
        self.assertIsInstance(out, ValueError)
        self.assertIn("did not exit", str(out))
        start.assert_not_called()
        self.assertGreater(call.call_count, 1)


if __name__ == "__main__":
    unittest.main()
