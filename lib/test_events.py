import json
import os
import sys
import tempfile
import unittest

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import dispatch  # noqa: E402
import events as ev  # noqa: E402


def pr(number, head, base, **kw):
    d = {"number": number, "title": kw.get("title", "PR %d" % number), "body": kw.get("body", ""),
         "state": kw.get("state", "OPEN"), "isDraft": False, "mergedAt": kw.get("mergedAt"),
         "headRefName": head, "baseRefName": base, "headRefOid": kw.get("sha", "a%d" % number),
         "reviewDecision": "", "latestReviews": kw.get("reviews", []), "comments": kw.get("comments", []),
         "statusCheckRollup": kw.get("checks", []), "url": "u"}
    return d


class FakeGitHub:
    def __init__(self):
        self.review, self.authored = [], []
        self.prs = {}

    def __call__(self, *args):
        if args[:2] == ("search", "prs"):
            refs = self.review if "--review-requested=@me" in args else self.authored
            return [{"repository": {"nameWithOwner": r.rsplit("#", 1)[0]}, "number": int(r.rsplit("#", 1)[1])}
                    for r in refs]
        if args[:2] == ("pr", "view"):
            return self.prs["%s#%s" % (args[args.index("-R") + 1], args[2])]
        if args[:2] == ("pr", "list"):
            repo = args[args.index("-R") + 1]
            return [p for r, p in self.prs.items() if r.startswith(repo + "#") and p["state"] == "OPEN"]
        raise AssertionError(args)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.world_path = os.path.join(self.tmp.name, "world.json")
        os.environ.update(HERDR_BIN=os.path.join(LIB, "testing", "fake_herdr.py"),
                          FAKE_HERDR_WORLD=self.world_path, PROMETHEUS_STATE_DIR=self.tmp.name,
                          PROMETHEUS_EXTERNAL="0", PROMETHEUS_REPOS="o/r", WORKSPACE=self.tmp.name,
                          PROMETHEUS_REPO_PROJECTS="o/r=besstie", PROMETHEUS_PROJECTS="besstie")
        self.gh = FakeGitHub()
        self._gh, ev.gh_json = ev.gh_json, self.gh
        self.created = []

    def tearDown(self):
        ev.gh_json = self._gh
        os.environ.pop("WORKSPACE", None)
        self.tmp.cleanup()

    def world(self):
        return json.load(open(self.world_path))

    def seat(self):
        import units
        ws = units._h("workspace", "create", "--label", "control", "--cwd", "/", "--no-focus")["workspace"]["workspace_id"]
        units.tag_pane(ws + ":p1", role="seat")
        w = self.world()
        w["panes"][-1]["agent_status"] = "idle"
        json.dump(w, open(self.world_path, "w"))
        return ws + ":p1"

    def fake_create(self, st, name, kind, project, stories, prs, scope):
        import units
        out = units.create(name, kind, project, stories, prs)
        self.created.append((name, kind, prs))
        return out["workspace"]


class GitHubTest(Base):
    def test_fingerprint_changes_are_next_move_only(self):
        a = ev.fingerprint(pr(1, "h", "main", checks=[{"conclusion": "SUCCESS"}]))
        b = dict(a, ci="fail", comments=2, review="bob:APPROVED", review_at="t2")
        self.assertEqual(ev.pr_changes("o/r#1", a, b), ["ci fail", "review bob:APPROVED", "2 new comment(s)"])
        self.assertEqual(ev.pr_changes("o/r#1", a, dict(a, ci="pending")), [])
        self.assertEqual(ev.pr_changes("o/r#1", None, a), ["new"])

    def test_bot_and_tool_comments_do_not_count(self):
        def c(login, body="hi"):
            return {"author": {"login": login}, "body": body}
        p = pr(1, "h", "main", comments=[
            c("shortcut-integration", "This pull request has been linked to [Shortcut Story #1"),
            c("vault-github-backend-integration", "<!-- PESTO_ARTIFACTS"),
            c("tylew", "* **#43658** <a href=\"https://app.graphite.com/github/pr/voltusdev/voltus/43658"),
            c("github-actions"), c("someone-human", "please rename this"), c("ci-noise-acct")],
            reviews=[{"author": {"login": "github-actions"}, "state": "COMMENTED", "submittedAt": "t1"}])
        f = ev.fingerprint(p, ignore=["ci-noise-acct"])
        self.assertEqual((f["comments"], f["review"]), (1, ""))

    def test_stack_walks_bases_and_children(self):
        self.gh.prs = {"o/r#1": pr(1, "a", "main"), "o/r#2": pr(2, "b", "a"), "o/r#3": pr(3, "c", "b"),
                       "o/r#9": pr(9, "z", "main")}
        self.assertEqual(ev.pr_stack("o/r#2"), ["o/r#1", "o/r#2", "o/r#3"])
        self.assertEqual(ev.pr_stack("o/r#9"), ["o/r#9"])

    def test_new_prs_capped_per_tick(self):
        self.gh.review = ["o/r#%d" % i for i in range(1, 6)]
        self.gh.prs = {r: pr(int(r[4:]), "h%s" % r, "main") for r in self.gh.review}
        with dispatch.locked_state() as st:
            first = ev.poll_github(dispatch.snapshot(), st)
            second = ev.poll_github(dispatch.snapshot(), st)
        self.assertEqual(len(first), ev.NEW_PER_TICK)
        self.assertEqual(len(second), 5 - ev.NEW_PER_TICK)

    def test_story_ids_from_pr(self):
        self.assertEqual(ev.stories_in("Fix it", "Closes sc-109610", "sc-109611-slug"), ["sc-109610", "sc-109611"])


class HandleTest(Base):
    def snap(self):
        return dispatch.snapshot()

    def test_review_request_auto_creates_one_unit_for_the_whole_stack(self):
        self.seat()
        self.gh.review = ["o/r#2"]
        self.gh.prs = {"o/r#1": pr(1, "a", "main"), "o/r#2": pr(2, "b", "a"), "o/r#3": pr(3, "c", "b")}
        verdict = {"decision": "new", "reason": "review", "proposal": {
            "kind": "review", "project": "besstie", "name": "review-1-thing", "prs": ["o/r#2"]}}
        with dispatch.locked_state() as st:
            events = ev.poll_github(self.snap(), st)
            log = ev.handle(self.snap(), st, events, triage_fn=lambda e, s: verdict, create_fn=self.fake_create)
        self.assertEqual(self.created, [("review-1-thing", "review", ["o/r#1", "o/r#2", "o/r#3"])])
        self.assertIn("created review unit", log[0])

    def test_stacked_pr_joins_existing_unit_without_triage(self):
        import units
        units.create("sc-1-a", "story", "besstie", ["sc-1"], ["o/r#1"])
        self.gh.authored = ["o/r#2"]
        self.gh.prs = {"o/r#1": pr(1, "a", "main"), "o/r#2": pr(2, "b", "a")}
        with dispatch.locked_state() as st:
            events = ev.poll_github(self.snap(), st)
            ev.handle(self.snap(), st, events, triage_fn=lambda e, s: self.fail("triaged"),
                      create_fn=self.fake_create)
            outbox = st["outbox"]
        unit = next(w for w in self.world()["workspaces"] if w.get("tokens", {}).get("unit") == "sc-1-a")
        self.assertEqual(unit["tokens"]["prs"], "o/r#1,o/r#2")
        self.assertTrue(any("o/r#2" in i["line"] for items in outbox.values() for i in items))

    def test_shortcut_story_becomes_a_seat_proposal_then_approve(self):
        seat = self.seat()
        story = {"kind": "story", "story": "sc-5", "state": "Backlog State", "change": "new",
                 "title": "Show X", "line": "[prometheus] story sc-5 new — Show X"}
        verdict = {"decision": "new", "reason": "assigned", "proposal": {
            "kind": "story", "project": "besstie", "name": "sc-5-show-x", "stories": ["sc-5"]}}
        with dispatch.locked_state() as st:
            ev.handle(self.snap(), st, [story], triage_fn=lambda e, s: verdict, create_fn=self.fake_create)
            line = st["outbox"][seat][0]["line"]
            pid = st["proposals"][0]["pid"]
        self.assertEqual(self.created, [])
        self.assertIn("proposal %s: new story unit sc-5-show-x" % pid, line)
        import units
        ev.create_unit = lambda st, *a: self.fake_create(st, *a)
        try:
            self.assertIn("approved", ev.proposal("approve", pid))
        finally:
            ev.create_unit = ev.__dict__["create_unit"]
        self.assertEqual(self.created[0][0], "sc-5-show-x")

    def test_ignored_and_already_seen_are_not_retriaged(self):
        calls = []
        story = {"kind": "story", "story": "sc-6", "state": "Backlog State", "change": "new", "title": "",
                 "line": "x"}
        with dispatch.locked_state() as st:
            ev.handle(self.snap(), st, [story], triage_fn=lambda e, s: calls.append(1) or {"decision": "ignore", "reason": "noise"})
            ev.handle(self.snap(), st, [story], triage_fn=lambda e, s: calls.append(1))
            ev.handle(self.snap(), st, [dict(story, change="Backlog State → Triage")], triage_fn=lambda e, s: calls.append(1))
        self.assertEqual(len(calls), 1)

    def test_token_loss_guard_turns_auto_create_into_a_proposal(self):
        self.seat()
        import units
        ws = units._h("workspace", "create", "--label", "sc-9-x", "--cwd", "/", "--no-focus")["workspace"]["workspace_id"]
        units._h("tab", "rename", ws + ":t1", "pm")
        self.gh.review = ["o/r#4"]
        self.gh.prs = {"o/r#4": pr(4, "d", "main")}
        verdict = {"decision": "new", "reason": "r", "proposal": {"kind": "review", "project": "p", "name": "review-4-d"}}
        with dispatch.locked_state() as st:
            events = ev.poll_github(self.snap(), st)
            log = ev.handle(self.snap(), st, events, triage_fn=lambda e, s: verdict, create_fn=self.fake_create)
        self.assertEqual(self.created, [])
        self.assertTrue(log[0].startswith("proposed"))

    def test_events_for_a_unit_awaiting_restore_are_held_for_it(self):
        events = [{"kind": "pr", "pr": "o/r#1", "source": "review-requested", "change": "new",
                   "title": "t", "line": "[prometheus] pr o/r#1 ci pass"}]
        with dispatch.locked_state() as st:
            st["image"] = {"sc-1-a": {"tokens": {"unit": "sc-1-a", "prs": "o/r#1"}, "agents": []}}
            log = ev.handle(self.snap(), st, events, triage_fn=lambda e, s: self.fail("triaged"),
                            create_fn=self.fake_create, stack_fn=lambda r, c: [r])
            self.assertEqual(st["restore_backlog"], {"sc-1-a": ["[prometheus] pr o/r#1 ci pass"]})
        self.assertIn("held for restore of sc-1-a", log[0])

    def test_completed_story_settles_kb(self):
        settled = []
        story = {"kind": "story", "story": "sc-7", "state": "Completed", "change": "In Development → Completed",
                 "line": "x"}
        with dispatch.locked_state() as st:
            ev.handle(self.snap(), st, [story], settle_fn=lambda s, state: settled.append((s, state)) or "ok")
        self.assertEqual(settled, [("sc-7", "Completed")])


class VerdictTest(Base):
    def test_invalid_verdict_goes_to_seat_untriaged(self):
        seat = self.seat()
        story = {"kind": "story", "story": "sc-8", "state": "Backlog State", "change": "new", "line": "[prometheus] story sc-8 new"}
        bad = {"decision": "new", "reason": "?", "proposal": {"kind": "story", "name": "sc-8-x", "project": "unknown"}}
        with dispatch.locked_state() as st:
            log = ev.handle(dispatch.snapshot(), st, [story], triage_fn=lambda e, s: bad, create_fn=self.fake_create)
            line = st["outbox"][seat][0]["line"]
        self.assertTrue(log[0].startswith("untriaged sc-8"))
        self.assertIn("untriaged: story sc-8 new", line)
        self.assertEqual(self.created, [])

    def test_pr_project_comes_from_the_repo_not_the_model(self):
        verdict = {"decision": "new", "reason": "r", "proposal": {"kind": "review", "name": "review-4-d", "project": "unknown"}}
        self.assertIsNone(ev.check_verdict({"kind": "pr", "pr": "o/r#4"}, verdict, dispatch.snapshot()))
        self.assertEqual(verdict["proposal"]["project"], "besstie")


class FilterTest(Base):
    def test_filter_skips_non_matching_subjects(self):
        os.environ["PROMETHEUS_FILTER"] = r"\[prometheus-test\]"
        calls = []
        evs = [{"kind": "story", "story": "sc-1", "state": "Backlog State", "change": "new", "title": "Real work", "line": "x"},
               {"kind": "story", "story": "sc-2", "state": "Backlog State", "change": "new", "title": "[prometheus-test] t", "line": "y"}]
        try:
            with dispatch.locked_state() as st:
                ev.handle(dispatch.snapshot(), st, evs, triage_fn=lambda e, s: calls.append(e["story"]) or {"decision": "ignore", "reason": "r"})
        finally:
            del os.environ["PROMETHEUS_FILTER"]
        self.assertEqual(calls, ["sc-2"])


class HealthTest(Base):
    def test_exited_lead_is_resumed_once(self):
        import units
        out = units.create("sc-1-a", "story", "besstie", ["sc-1"], [])
        w = self.world()
        p = next(x for x in w["panes"] if x["pane_id"] == out["pane"])
        p.update(agent="claude", agent_session={"value": "sess-1"})
        json.dump(w, open(self.world_path, "w"))
        with dispatch.locked_state() as st:
            self.assertEqual(ev.health(dispatch.snapshot(), st), [])
            w = self.world()
            next(x for x in w["panes"] if x["pane_id"] == out["pane"]).pop("agent")
            json.dump(w, open(self.world_path, "w"))
            first = ev.health(dispatch.snapshot(), st)
            second = ev.health(dispatch.snapshot(), st)
        self.assertIn("resumed pm", first[0])
        self.assertEqual(second, [])
        ran = next(x for x in self.world()["panes"] if x["pane_id"] == out["pane"])["ran"]
        self.assertIn("--resume sess-1", ran)


    def test_exited_librarian_restarts_fresh(self):
        w = {"workspaces": [{"workspace_id": "wC", "label": "control"}], "tabs": [], "panes": []}
        w["panes"].append({"pane_id": "wC:p9", "tab_id": "wC:t9", "workspace_id": "wC", "agent_status": "unknown",
                           "tokens": {"role": "librarian"}})
        json.dump(w, open(self.world_path, "w"))
        with dispatch.locked_state() as st:
            log = ev.health(dispatch.snapshot(), st)
        ran = next(x for x in self.world()["panes"] if x["pane_id"] == "wC:p9")["ran"]
        self.assertEqual(log, ["restarted librarian in wC:p9"])
        self.assertIn("--agent prometheus:librarian", ran)
        self.assertNotIn("--resume", ran)

if __name__ == "__main__":
    unittest.main()
