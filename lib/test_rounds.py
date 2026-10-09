import os
import sys
import tempfile
import unittest

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import dispatch as d  # noqa: E402
import rounds  # noqa: E402

REF = "o/r#10"


def snap(impl=False, reviewer=None):
    panes = [{"pane_id": "wA:p1", "workspace_id": "wA", "agent_status": "idle", "tokens": {"role": "pm"}}]
    if impl:
        panes.append({"pane_id": "wA:p2", "workspace_id": "wA", "tab_id": "wA:t2", "agent_status": "idle",
                      "tokens": {"role": "implementor", "item": "x", "pr": REF}})
    if reviewer:
        panes.append({"pane_id": "wA:p3", "workspace_id": "wA", "tab_id": "wA:t3", "agent_status": reviewer,
                      "tokens": {"role": "reviewer", "pr": REF}})
    return {"workspaces": [{"workspace_id": "wA", "label": "epic-1-x",
                            "tokens": {"unit": "epic-1-x", "kind": "epic", "epic": "1", "prs": REF}}],
            "panes": panes, "tabs": [{"tab_id": "wA:t3", "label": "review-10"}]}


def ev(*changes, author="mate"):
    return {"kind": "pr", "pr": REF, "changes": list(changes), "author": author, "head": "h2", "title": "t"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PROMETHEUS_STATE_DIR"] = self.tmp.name
        os.environ.pop("PROMETHEUS_ROLE", None)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("PROMETHEUS_STATE_DIR", None)

    def brief(self, n=1):
        path = os.path.join(self.tmp.name, "b.md")
        with open(path, "w") as fh:
            fh.write("---\npr: %s\nround: %d\nartifact: /s/reviews/o-r-10-r%d.md\n---\n# Review\n" % (REF, n, n))
        return path


class TargetsTest(Base):
    def t(self, s, e, st=None):
        st = st if st is not None else {}
        return rounds.targets(s, st, s["workspaces"][0], e, operator="me"), st

    def test_lifecycle_changes_reach_the_pm_and_end_the_loop(self):
        st = {"loops": {REF: {"brief": "b", "round": 1}}}
        out, st = self.t(snap(impl=True), ev("merged", "ci pass"), st)
        self.assertEqual(out, {"wA:p1": ["merged"], "wA:p2": ["ci pass"]})
        self.assertNotIn(REF, st["loops"])

    def test_a_teammates_ci_reaches_no_one_without_a_holder(self):
        self.assertEqual(self.t(snap(), ev("ci fail"))[0], {})
        self.assertEqual(self.t(snap(), ev("ci fail", author="me"))[0], {"wA:p1": ["ci fail"]})

    def test_comments_go_to_the_holder_else_the_pm(self):
        self.assertEqual(self.t(snap(impl=True), ev("2 new comment(s)"))[0], {"wA:p2": ["2 new comment(s)"]})
        self.assertEqual(self.t(snap(), ev("2 new comment(s)"))[0], {"wA:p1": ["2 new comment(s)"]})

    def test_new_commits_in_the_loop_schedule_a_round_not_a_line(self):
        out, st = self.t(snap(), ev("new commits"), {"loops": {REF: {"brief": "b", "round": 1}}})
        self.assertEqual(out, {})
        self.assertEqual(st["loops"][REF]["head"], "h2")
        self.assertIn("due", st["loops"][REF])

    def test_new_commits_reach_a_working_reviewer_or_the_pm_when_held(self):
        self.assertEqual(self.t(snap(reviewer="working"), ev("new commits"))[0], {"wA:p3": ["new commits"]})
        held = {"loops": {REF: {"brief": "b", "round": 1, "held": True}}}
        self.assertEqual(self.t(snap(), ev("new commits"), held)[0], {"wA:p1": ["new commits"]})


class FireTest(Base):
    def test_next_brief_bumps_round_and_artifact_and_puts_the_due_check_first(self):
        path = rounds.next_brief({"brief": self.brief(2), "round": 2}, REF, "h3")
        text = open(path).read()
        self.assertIn("round: 3", text)
        self.assertIn("artifact: /s/reviews/o-r-10-r3.md", text)
        self.assertIn("Is a round due?", text)
        self.assertTrue(path.endswith("o-r-10-r3.md"))

    def test_a_due_round_opens_and_the_pm_hears_one_line(self):
        st = {"cursors": {"pr:" + REF: {"state": "open", "head": "h2"}}, "outbox": {}, "last_change": {},
              "loops": {REF: {"unit": "epic-1-x", "workspace": "wA", "brief": self.brief(), "round": 1,
                              "due": 1, "head": "h2"}}}
        opened = []
        log = rounds.fire(snap(), st, now=10, opener=lambda s, ws, label, ref, b: opened.append(label) or "wA:p9")
        self.assertEqual((opened, log), (["review-10"], ["auto round 2 on o/r#10"]))
        self.assertEqual(st["loops"][REF]["round"], 2)
        self.assertNotIn("due", st["loops"][REF])
        self.assertIn("auto round 2", st["outbox"]["wA:p1"][0]["line"])

    def test_no_round_when_the_head_moved_held_or_draft(self):
        base = {"unit": "epic-1-x", "workspace": "wA", "brief": self.brief(), "round": 1, "due": 1, "head": "h2"}
        for cur, extra in (({"state": "open", "head": "h3"}, {}), ({"state": "open", "head": "h2"}, {"held": True}),
                           ({"state": "open", "head": "h2", "draft": True}, {})):
            st = {"cursors": {"pr:" + REF: cur}, "outbox": {}, "last_change": {}, "loops": {REF: dict(base, **extra)}}
            self.assertEqual(rounds.fire(snap(), st, now=10, opener=lambda *a: self.fail("opened")), [])


class UnfinishedRoundTest(Base):
    def st(self):
        return {"cursors": {"pr:" + REF: {"state": "open", "head": "h2"}}, "outbox": {}, "last_change": {},
                "loops": {REF: {"unit": "epic-1-x", "workspace": "wA", "brief": "b", "round": 1, "due": 1,
                                "head": "h2"}}}

    def test_an_idle_reviewer_with_no_findings_is_not_closed_by_the_next_round(self):
        st = self.st()
        log = rounds.fire(snap(reviewer="idle"), st, now=10, opener=lambda *a: self.fail("opened"))
        self.assertIn("round 1 on o/r#10 has no findings file yet — not reopened", log)
        self.assertEqual(st["loops"][REF]["due"], 1)

    def test_with_its_findings_written_the_next_round_opens(self):
        os.makedirs(os.path.join(self.tmp.name, "reviews"), exist_ok=True)
        open(rounds.findings_path(REF, 1), "w").close()
        opened = []
        st = self.st()
        st["loops"][REF]["brief"] = os.path.join(self.tmp.name, "b.md")
        with open(st["loops"][REF]["brief"], "w") as fh:
            fh.write("round: 1\n")
        rounds.fire(snap(reviewer="idle"), st, now=10, opener=lambda s, ws, label, ref, b: opened.append(label) or "wA:p9")
        self.assertEqual(opened, ["review-10"])


class NextTest(Base):
    def test_next_makes_the_round_due_now_and_lifts_a_hold(self):
        st = {"cursors": {"pr:" + REF: {"head": "h5"}}, "loops": {REF: {"round": 1, "held": True}}}
        rounds.now_due(st, REF)
        self.assertEqual((st["loops"][REF]["due"], st["loops"][REF]["head"], st["loops"][REF]["held"]), (1, "h5", False))
        with self.assertRaisesRegex(ValueError, "not in a review loop"):
            rounds.now_due(st, "o/r#99")

    def test_an_own_prs_new_commits_wait_for_next(self):
        s = snap()
        st = {"loops": {REF: {"brief": "b", "round": 1}}}
        out = rounds.targets(s, st, s["workspaces"][0], ev("new commits", author="me"), operator="me")
        self.assertEqual(out, {"wA:p1": ["new commits"]})
        self.assertNotIn("due", st["loops"][REF])


class SendToHolderTest(Base):
    def test_send_pr_reaches_the_implementor_holding_it(self):
        os.environ["HERDR_PANE_ID"] = "wA:p3"
        try:
            with d.locked_state() as st:
                self.assertEqual(d.send(snap(impl=True, reviewer="working"), st, "findings", role="implementor",
                                        pr=REF), "wA:p2")
                with self.assertRaisesRegex(d.RouteError, "no implementor holds"):
                    d.send(snap(reviewer="working"), st, "findings", role="implementor", pr=REF)
        finally:
            os.environ.pop("HERDR_PANE_ID", None)


if __name__ == "__main__":
    unittest.main()
