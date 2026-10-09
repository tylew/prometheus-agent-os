import json
import os
import sys
import tempfile
import unittest
import unittest.mock

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import dispatch as d  # noqa: E402
import unit_engine as eng  # noqa: E402


def snap(engine="on", stages="sc-1=review,sc-2=ready"):
    tokens = {"unit": "epic-1-x", "kind": "epic", "stories": "sc-1,sc-2,sc-3", "stages": stages}
    if engine:
        tokens["engine"] = engine
    return {"workspaces": [{"workspace_id": "wA", "label": "epic-1-x", "tokens": tokens},
                           {"workspace_id": "wB", "label": "epic-2-y", "tokens": {"unit": "epic-2-y", "stories": "sc-9"}}],
            "panes": [{"pane_id": "wA:p1", "workspace_id": "wA", "agent_status": "idle", "tokens": {"role": "pm"}}]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PROMETHEUS_STATE_DIR"] = self.tmp.name
        self.patch = unittest.mock.patch.object(d, "pending_restore", return_value={})
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()
        os.environ.pop("PROMETHEUS_STATE_DIR", None)

    def feed(self, unit="epic-1-x"):
        return eng.tail(unit, 100)

    def inbox(self, kind, story, unit="epic-1-x", name="1-x.json"):
        box = eng.inbox_dir()
        os.makedirs(box, exist_ok=True)
        with open(os.path.join(box, name), "w") as fh:
            json.dump({"kind": kind, "file": "/tmp/%s.md" % kind, "pane": "wA:p2", "role": "implementor",
                       "story": story, "unit": unit, "at": 1}, fh)


class AdoptTest(Base):
    def test_stories_are_adopted_once_and_past_ready_is_legacy(self):
        st = {}
        log = eng.tick(snap(), st, now=1)
        recs = st["engine"]["stories"]
        self.assertEqual((recs["sc-1"]["stage"], recs["sc-1"]["legacy"]), ("review", True))
        self.assertEqual((recs["sc-2"]["stage"], recs["sc-2"]["legacy"]), ("ready", False))
        self.assertEqual((recs["sc-3"]["stage"], recs["sc-3"]["legacy"]), ("backlog", False))
        self.assertEqual(len([l for l in log if "adopted" in l]), 3)
        self.assertEqual([l for l in eng.tick(snap(), st, now=2) if "adopted" in l], [])
        self.assertNotIn("sc-9", recs)

    def test_off_units_are_not_tracked(self):
        st = {}
        eng.tick(snap(engine=None), st, now=1)
        self.assertEqual(st.get("engine", {}).get("stories", {}), {})

    def test_waits_for_restore(self):
        st = {}
        with unittest.mock.patch.object(d, "pending_restore", return_value={"epic-1-x": {}}):
            self.assertEqual(eng.tick(snap(), st, now=1), ["engine: waiting for restore"])
        self.assertEqual(st, {})


class InboxTest(Base):
    def test_reports_move_the_story_and_land_in_the_feed(self):
        st = {}
        eng.tick(snap(stages=""), st, now=1)
        self.inbox("idr", "sc-2", name="1-a.json")
        self.inbox("stopped", "sc-3", name="2-b.json")
        eng.tick(snap(stages=""), st, now=2)
        recs = st["engine"]["stories"]
        self.assertEqual((recs["sc-2"]["stage"], recs["sc-2"]["waiting"]), ("design", "IDR check"))
        self.assertEqual((recs["sc-3"]["stage"], recs["sc-3"]["waiting"]), ("stopped", "the stop's owner"))
        self.assertEqual(recs["sc-3"]["files"]["stopped"], "/tmp/stopped.md")
        self.assertEqual(os.listdir(eng.inbox_dir()), ["done"])
        self.assertTrue(any("sc-3: backlog → stopped" in l for l in self.feed()))

    def test_a_report_for_an_engine_off_unit_is_only_fed(self):
        st = {}
        self.inbox("done", "sc-9", unit="epic-2-y")
        eng.tick(snap(), st, now=1)
        self.assertNotIn("sc-9", st["engine"]["stories"])
        self.assertTrue(any("inbox done from implementor" in l for l in self.feed("epic-2-y")))


class ShadowTest(Base):
    def test_a_pm_engine_disagreement_is_fed_once(self):
        st = {}
        eng.tick(snap(stages=""), st, now=1)
        self.inbox("idr", "sc-2")
        eng.tick(snap(stages=""), st, now=2)
        eng.tick(snap(stages="sc-2=implement"), st, now=3)
        eng.tick(snap(stages="sc-2=implement"), st, now=4)
        lines = [l for l in self.feed() if "shadow: sc-2" in l]
        self.assertEqual(len(lines), 1)
        self.assertIn("PM says implement, engine says design", lines[0])

    def test_observe_feeds_only_engine_units(self):
        eng.observe(snap(), {"unit": "epic-1-x", "line": "[prometheus] CI green on o/r#10"})
        eng.observe(snap(), {"unit": "epic-2-y", "line": "[prometheus] CI green on o/r#99"})
        self.assertTrue(any("CI green on o/r#10" in l for l in self.feed()))
        self.assertEqual(self.feed("epic-2-y"), [])


class IntentTest(Base):
    def test_an_intent_is_recorded_once(self):
        rec = eng.story_state({}, "sc-1", "epic-1-x")
        self.assertTrue(eng.intend(rec, "counts", "r2:abc1234"))
        self.assertFalse(eng.intend(rec, "counts", "r2:abc1234"))
        self.assertTrue(eng.intend(rec, "counts", "r3:def5678"))

    def test_acting_reads_the_unit_token(self):
        u = {"tokens": {"engine": "on", "engine_act": "review,stops"}}
        self.assertTrue(eng.acting(u, "stops"))
        self.assertFalse(eng.acting(u, "pull"))


class MergeAndHeartbeatTest(Base):
    def test_nested_records_merge_per_field(self):
        base = {"loops": {"o/r#1": {"round": 1, "held": False, "due": 1}}}
        work = {"loops": {"o/r#1": {"round": 2, "held": False}}}
        st = {"loops": {"o/r#1": {"round": 1, "held": True, "due": 1}}}
        d.merge_state(base, work, st)
        self.assertEqual(st["loops"]["o/r#1"], {"round": 2, "held": True})

    def test_waiting_panes_are_never_nudged(self):
        s = {"workspaces": [{"workspace_id": "wA", "tokens": {"unit": "u"}}],
             "panes": [{"pane_id": "wA:p2", "workspace_id": "wA", "agent_status": "idle",
                        "tokens": {"role": "implementor", "status": "stopped: needs the product owner", "needs": "1"}}]}
        st = {"last_change": {"u": 0}, "beats": {}}
        self.assertEqual(d.heartbeat(s, st, 30, now=10_000), [])
        s["panes"][0]["tokens"] = {"role": "implementor", "status": "building"}
        self.assertEqual(len(d.heartbeat(s, st, 30, now=10_000)), 1)


if __name__ == "__main__":
    unittest.main()
