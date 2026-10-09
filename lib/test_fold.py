import json
import os
import sys
import tempfile
import unittest

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import dispatch  # noqa: E402
import events  # noqa: E402
import fold  # noqa: E402
import units  # noqa: E402

EPICS = {"sc-1001": ("77", "MISO / Ameren"), "sc-1002": ("77", "MISO / Ameren"), "sc-1003": ("", "")}


def lookup(st, ids, fn=None, now=None):
    for i in ids:
        events.remember_epic(st, i, *EPICS.get(i, ("", "")))


class FoldTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.world_path = os.path.join(self.tmp.name, "world.json")
        os.environ.update(HERDR_BIN=os.path.join(LIB, "testing", "fake_herdr.py"), FAKE_HERDR_WORLD=self.world_path,
                          PROMETHEUS_STATE_DIR=self.tmp.name, WORKSPACE=self.tmp.name, PROMETHEUS_DEFAULT_PROJECT="besstie")
        self.a = units.create("sc-1001-a", "story", "besstie", ["sc-1001"], ["o/r#10"])["workspace"]
        self.b = units.create("review-11-b", "review", "besstie", ["sc-1002"], ["o/r#11", "o/r#12"])["workspace"]
        self.c = units.create("sc-1003-c", "story", "besstie", ["sc-1003"], [])["workspace"]

    def tearDown(self):
        for k in ("HERDR_BIN", "FAKE_HERDR_WORLD", "PROMETHEUS_STATE_DIR", "WORKSPACE", "PROMETHEUS_DEFAULT_PROJECT"):
            os.environ.pop(k, None)
        self.tmp.cleanup()

    def test_plan_groups_by_epic_and_names_the_unhomed(self):
        p = fold.plan(dispatch.snapshot(), lookup)
        e = p["epics"]["77"]
        self.assertEqual((e["unit"], e["units"], e["stories"], e["prs"]),
                         ("epic-77-miso-ameren", ["sc-1001-a", "review-11-b"], ["sc-1001", "sc-1002"],
                          ["o/r#10", "o/r#11", "o/r#12"]))
        self.assertEqual(p["unhomed"], ["sc-1003-c"])

    def test_run_waits_for_handoffs_then_opens_the_epic_and_closes_the_old_units(self):
        path = fold.epic_file("epic-77-miso-ameren")
        writes = iter(["## from review-11-b\nr1 approved\n", "## from sc-1001-a\nimplement\n"])

        def sleep(_):
            with open(path, "a") as fh:
                fh.write(next(writes, ""))
        out = fold.run("77", wait=5, lookup=lookup, sleep=sleep)
        self.assertEqual(sorted(out["folded"]), ["review-11-b", "sc-1001-a"])
        w = json.load(open(self.world_path))
        live = {(x.get("tokens") or {}).get("unit"): x["tokens"] for x in w["workspaces"] if (x.get("tokens") or {}).get("unit")}
        self.assertEqual(sorted(live), ["epic-77-miso-ameren", "sc-1003-c"])
        t = live["epic-77-miso-ameren"]
        self.assertEqual((t["kind"], t["epic"], t["stories"], t["prs"]),
                         ("epic", "77", "sc-1001,sc-1002", "o/r#10,o/r#11,o/r#12"))
        with dispatch.locked_state() as st:
            lines = [i["line"] for items in st["outbox"].values() for i in items]
        self.assertTrue(any("write your handoff" in l for l in lines))

    def test_a_busy_old_unit_stays_open_tagged_folded(self):
        w = json.load(open(self.world_path))
        w["panes"].append({"pane_id": "%s:p9" % self.a, "tab_id": "t9", "workspace_id": self.a,
                           "agent_status": "working", "tokens": {"role": "implementor"}})
        json.dump(w, open(self.world_path, "w"))
        path = fold.epic_file("epic-77-miso-ameren")
        with open(path, "a") as fh:
            fh.write("## from review-11-b\n## from sc-1001-a\n")
        out = fold.run("77", wait=5, lookup=lookup, sleep=lambda _: None)
        self.assertEqual(out["folded"], ["review-11-b"])
        snap = dispatch.snapshot()
        self.assertEqual(dispatch._tokens(dispatch.unit_of_workspace(snap, self.a)).get("folded"), "epic-77-miso-ameren")
        epic = next(u for u in dispatch.units(snap) if dispatch._tokens(u)["unit"] == "epic-77-miso-ameren")
        self.assertEqual(dispatch.match_units(snap, {"story": "sc-1001"}), [epic])

    def test_run_opens_nothing_until_every_handoff_is_written(self):
        out = fold.run("77", wait=0.01, lookup=lookup, sleep=lambda _: None)
        self.assertEqual(out["folded"], [])
        self.assertEqual(sorted(out["waiting"]), ["review-11-b", "sc-1001-a"])
        names = [(x.get("tokens") or {}).get("unit") for x in json.load(open(self.world_path))["workspaces"]]
        self.assertNotIn("epic-77-miso-ameren", names)


if __name__ == "__main__":
    unittest.main()
