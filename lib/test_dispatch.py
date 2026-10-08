import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import dispatch as d  # noqa: E402


def snap(**over):
    s = {
        "workspaces": [
            {"workspace_id": "wC", "label": "control", "tokens": {"dispatcher": "running"}},
            {"workspace_id": "wA", "label": "sc-1-a", "tokens": {"unit": "sc-1-a", "kind": "story", "stories": "sc-1", "prs": "o/r#10,o/r#11"}},
            {"workspace_id": "wB", "label": "goal-x", "tokens": {"unit": "goal-x", "kind": "goal-set", "stories": "sc-2"}},
        ],
        "panes": [
            {"pane_id": "wC:p1", "workspace_id": "wC", "agent_status": "idle", "tokens": {"role": "seat"}},
            {"pane_id": "wA:p1", "workspace_id": "wA", "agent_status": "idle", "tokens": {"role": "pm"}},
            {"pane_id": "wA:p2", "workspace_id": "wA", "agent_status": "working", "tokens": {"role": "implementor", "item": "derate"}},
            {"pane_id": "wA:p3", "workspace_id": "wA", "agent_status": "idle", "tokens": {"role": "reviewer", "pr": "o/r#10"}},
            {"pane_id": "wB:p1", "workspace_id": "wB", "agent_status": "blocked", "tokens": {"role": "planner"}},
        ],
    }
    s.update(over)
    return s


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PROMETHEUS_STATE_DIR"] = self.tmp.name
        os.environ["PROMETHEUS_EXTERNAL"] = "0"
        for k in ("PROMETHEUS_ROLE", "HERDR_WORKSPACE_ID"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("PROMETHEUS_STATE_DIR", None)


class RouteTest(Base):
    def test_story_pr_and_stack_route_to_pm(self):
        s = snap()
        self.assertEqual(d.route(s, {"story": "sc-1"}), "wA:p1")
        self.assertEqual(d.route(s, {"pr": "o/r#11"}), "wA:p1")
        self.assertEqual(d.route(s, {"pr": "o/r#99", "stack": ["o/r#10"]}), "wA:p1")

    def test_bare_story_token_still_matches(self):
        s = snap()
        s["workspaces"][1]["tokens"]["stories"] = "1"
        self.assertEqual(d.route(s, {"story": "sc-1"}), "wA:p1")

    def test_planner_is_a_child_reached_by_role(self):
        s = snap()
        s["workspaces"][2]["tokens"]["kind"] = "goal-set"
        s["panes"].append({"pane_id": "wB:p0", "workspace_id": "wB", "agent_status": "idle", "tokens": {"role": "pm"}})
        self.assertEqual(d.route(s, {"story": "sc-2"}), "wB:p0")
        self.assertEqual(d.route(s, {"story": "sc-2", "role": "planner"}), "wB:p1")

    def test_seat_and_role_within_unit(self):
        s = snap()
        self.assertEqual(d.route(s, {"role": "seat"}), "wC:p1")
        self.assertEqual(d.route(s, {"unit": "sc-1-a", "role": "implementor", "item": "derate"}), "wA:p2")

    def test_control_roles_prefer_the_running_dispatchers_workspace(self):
        s = snap()
        s["workspaces"][0]["tokens"] = {}  # an old trial control workspace, dispatcher stopped
        s["workspaces"].append({"workspace_id": "wR", "label": "real", "tokens": {"dispatcher": "running"}})
        s["panes"].append({"pane_id": "wR:p1", "workspace_id": "wR", "agent_status": "idle", "tokens": {"role": "seat"}})
        self.assertEqual(d.route(s, {"role": "seat"}), "wR:p1")

    def test_conflict_and_no_match_raise(self):
        s = snap()
        s["workspaces"][2]["tokens"]["prs"] = "o/r#10"
        with self.assertRaisesRegex(d.RouteError, "CONFLICT"):
            d.route(s, {"pr": "o/r#10"})
        with self.assertRaisesRegex(d.RouteError, "no unit"):
            d.route(snap(), {"story": "sc-404"})


class SendDeliverTest(Base):
    def test_send_defaults_to_own_unit_and_tags_sender(self):
        os.environ.update(PROMETHEUS_ROLE="implementor", HERDR_WORKSPACE_ID="wA")
        with d.locked_state() as st:
            target = d.send(snap(), st, "done: report at /x", role="pm")
        self.assertEqual(target, "wA:p1")
        with d.locked_state() as st:
            self.assertEqual(st["outbox"]["wA:p1"][0]["line"], "[prometheus] from implementor@sc-1-a: done: report at /x")

    def test_blocked_target_is_held_then_delivered(self):
        sent = []
        with d.locked_state() as st:
            d.enqueue(st, "wB:p1", "[prometheus] hello")
            r = d.deliver(snap(), st, prompt=lambda p, t: sent.append((p, t)))
        self.assertEqual((r["held"], sent), (["wB:p1"], []))
        s = snap()
        s["panes"][4]["agent_status"] = "idle"
        with d.locked_state() as st:
            r = d.deliver(s, st, prompt=lambda p, t: sent.append((p, t)))
            self.assertNotIn("wB:p1", st["outbox"])
        self.assertEqual(sent, [("wB:p1", "[prometheus] hello")])

    def test_many_messages_coalesce_into_one_prompt_with_details(self):
        sent = []
        with d.locked_state() as st:
            for i in range(3):
                d.enqueue(st, "wA:p1", "[prometheus] event %d" % i)
            d.deliver(snap(), st, prompt=lambda p, t: sent.append(t))
        self.assertEqual(len(sent), 1)
        self.assertIn("3 messages", sent[0])
        path = sent[0].rsplit("details: ", 1)[1]
        self.assertEqual(len(json.load(open(path))), 3)

    def test_open_dialog_or_typed_input_holds_delivery(self):
        world = os.path.join(self.tmp.name, "world.json")
        s = snap()
        s["panes"][1]["screen"] = "Enter to select · ↑/↓ to navigate · Esc to cancel"
        s["panes"][0]["input"] = "half-typed by the operator"
        json.dump(s, open(world, "w"))
        os.environ.update(HERDR_BIN=os.path.join(LIB, "testing", "fake_herdr.py"), FAKE_HERDR_WORLD=world)
        try:
            self.assertEqual(d.input_busy("wA:p1"), "dialog open")
            self.assertEqual(d.input_busy("wC:p1"), "input line not empty")
            self.assertIsNone(d.input_busy("wA:p2"))
            with d.locked_state() as st:
                d.enqueue(st, "wA:p1", "x")
                r = d.deliver(s, st)
            self.assertEqual(r["held"], ["wA:p1"])
        finally:
            for k in ("HERDR_BIN", "FAKE_HERDR_WORLD"):
                os.environ.pop(k)

    def test_vanished_pane_is_dropped(self):
        with d.locked_state() as st:
            d.enqueue(st, "wZ:p9", "x")
            r = d.deliver(snap(), st, prompt=lambda p, t: None)
        self.assertEqual(r["dropped"], ["wZ:p9"])


class LibrarianReportTest(Base):
    def lib_snap(self):
        s = snap()
        s["panes"].append({"pane_id": "wC:p2", "workspace_id": "wC", "agent_status": "idle",
                           "tokens": {"role": "librarian"}})
        return s

    def test_the_librarian_tab_is_never_cleared_by_delivery(self):
        os.environ.update(PROMETHEUS_ROLE="seat", HERDR_WORKSPACE_ID="wC")
        sent = []
        with d.locked_state() as st:
            d.enqueue(st, "wC:p2", "[prometheus] a note for the operator's librarian")
            d.deliver(self.lib_snap(), st, prompt=lambda p, t: sent.append(t))
        self.assertNotIn("/clear", sent)

    def test_needs_you_flags_the_pane_and_asks_the_seat(self):
        world = os.path.join(self.tmp.name, "world.json")
        json.dump(snap(), open(world, "w"))
        os.environ.update(HERDR_BIN=os.path.join(LIB, "testing", "fake_herdr.py"), FAKE_HERDR_WORLD=world,
                          HERDR_PANE_ID="wA:p1")
        try:
            with d.locked_state() as st:
                d.report(d.snapshot(), st, "v1 or v2 API?", needs=True)
                line = st["outbox"]["wC:p1"][0]["line"]
            toks = json.load(open(world))["panes"][1]["tokens"]
            self.assertEqual((toks["status"], toks["needs"]), ("v1 or v2 API?", "1"))
            self.assertIn("needs you — pm@sc-1-a (wA:p1): v1 or v2 API?", line)
            w = json.load(open(world))
            w["panes"][1]["agent_status"] = "working"
            json.dump(w, open(world, "w"))
            with d.locked_state() as st:
                d.poll_agents(d.snapshot(), st)
            self.assertNotIn("needs", json.load(open(world))["panes"][1]["tokens"])
        finally:
            for k in ("HERDR_BIN", "FAKE_HERDR_WORLD", "HERDR_PANE_ID"):
                os.environ.pop(k)

    def test_open_dialog_is_flagged_to_the_seat_once(self):
        s = snap()
        with d.locked_state() as st, unittest.mock.patch.object(d, "herdr") as h:
            first = d.dialogs(s, st, probe=lambda p: "dialog open" if p == "wA:p3" else None)
            again = d.dialogs(s, st, probe=lambda p: "dialog open" if p == "wA:p3" else None)
            closed = d.dialogs(s, st, probe=lambda p: None)
        self.assertEqual([e["pane"] for e in first], ["wA:p3"])
        self.assertIn("reviewer@sc-1-a (wA:p3) has a question open", first[0]["line"])
        self.assertEqual((again, closed, st["dialogs"]), ([], [], {}))
        h.assert_called_once()

    def test_blocked_runner_asks_the_seat(self):
        s = snap()
        s["panes"].append({"pane_id": "wC:p5", "workspace_id": "wC", "agent_status": "working",
                           "tokens": {"role": "runner", "item": "curves"}})
        with d.locked_state() as st:
            d.poll_agents(s, st)
            s["panes"][-1]["agent_status"] = "blocked"
            evs = d.poll_agents(s, st)
        self.assertEqual([(e["route_role"], e["pane"]) for e in evs], [("seat", "wC:p5")])
        self.assertIn("quick-curves (wC:p5) is waiting on a permission prompt", evs[0]["line"])

    def test_image_keeps_units_that_vanish(self):
        s = snap()
        s["tabs"] = [{"tab_id": "wA:t1", "label": "pm"}]
        s["panes"][1].update(tab_id="wA:t1", agent_session={"value": "s1"})
        with d.locked_state() as st:
            d.update_image(s, st)
            gone = snap(workspaces=[w for w in snap()["workspaces"] if w["workspace_id"] != "wA"])
            d.update_image(gone, st)
            pending = d.pending_restore(gone, st)
        self.assertEqual(list(pending), ["sc-1-a"])
        self.assertEqual(pending["sc-1-a"]["agents"][0], {"label": "pm", "tokens": {"role": "pm"}, "session": "s1"})

    def test_test_units_only_seen_with_flag(self):
        s = snap()
        s["workspaces"].append({"workspace_id": "wT", "tokens": {"unit": "prom-test-x"}})
        with d.locked_state() as st:
            st["image"]["prom-test-old"] = {"tokens": {"unit": "prom-test-old"}, "agents": []}
            self.assertNotIn("prom-test-x", [d._tokens(u)["unit"] for u in d.units(s)])
            self.assertIn("sc-1-a", [d._tokens(u)["unit"] for u in d.units(s)])
            self.assertNotIn("prom-test-old", d.pending_restore(s, st))
            d.update_image(s, st)
            self.assertFalse([k for k in st["image"] if k.startswith("prom-test-")])
            os.environ["PROMETHEUS_TEST_UNITS"] = "1"
            try:
                st["image"]["prom-test-old"] = {"tokens": {"unit": "prom-test-old"}, "agents": []}
                self.assertIn("prom-test-x", [d._tokens(u)["unit"] for u in d.units(s)])
                self.assertIn("prom-test-old", d.pending_restore(s, st))
                d.update_image(s, st)
                self.assertIn("prom-test-x", st["image"])
            finally:
                os.environ.pop("PROMETHEUS_TEST_UNITS")


class MergeTest(Base):
    def test_concurrent_send_survives_an_external_tick(self):
        base = {"outbox": {"wA:p1": [{"line": "a"}]}, "ignored": ["x"], "proposals": [{"pid": "p1"}],
                "cursors": {"gh": 1, "sc": 1}}
        work = copy.deepcopy(base)
        work["outbox"]["wA:p1"].append({"line": "from-tick"})
        work["ignored"].append("y")
        work["proposals"].append({"pid": "p2"})
        work["cursors"]["gh"] = 2
        st = copy.deepcopy(base)
        st["outbox"]["wC:p1"] = [{"line": "from-send"}]   # written by send.sh meanwhile
        st["proposals"] = []                              # p1 answered by proposal.sh meanwhile
        st["cursors"]["sc"] = 5
        d.merge_state(base, work, st)
        self.assertEqual(st["outbox"], {"wA:p1": [{"line": "a"}, {"line": "from-tick"}],
                                        "wC:p1": [{"line": "from-send"}]})
        self.assertEqual((st["ignored"], st["proposals"], st["cursors"]),
                         (["x", "y"], [{"pid": "p2"}], {"gh": 2, "sc": 5}))

    def test_a_queued_slash_command_is_sent_alone_after_the_messages(self):
        sent = []
        with d.locked_state() as st:
            d.enqueue(st, "wA:p1", "/compact keep: epic 77")
            d.enqueue(st, "wA:p1", "[prometheus] ci pass")
            d.deliver(snap(), st, prompt=lambda p, t: sent.append(t))
        self.assertEqual(sent, ["[prometheus] ci pass", "/compact keep: epic 77"])

    def test_a_failed_send_is_requeued(self):
        def boom(p, t):
            raise RuntimeError("herdr down")
        with d.locked_state() as st:
            d.enqueue(st, "wA:p1", "[prometheus] x")
        with d.locked_state() as st:
            report, sends = d.take_deliveries(snap(), st, real=False)
        self.assertEqual(d.send_all(sends, boom), sends)


class AgentsHeartbeatTest(Base):
    def test_depth3_finish_goes_to_pm_lead_block_goes_to_seat(self):
        with d.locked_state() as st:
            self.assertEqual(d.poll_agents(snap(), st), [])
            s = snap()
            s["panes"][2]["agent_status"] = "idle"
            s["panes"][1]["agent_status"] = "working"
            evs = d.poll_agents(s, st)
        self.assertEqual([(e["pane"], e["route_role"]) for e in evs], [("wA:p2", "pm")])
        self.assertIn("derate working → idle", evs[0]["line"])

    def test_heartbeat_once_per_quiet_spell(self):
        now, s = time.time(), snap()
        s["panes"][2]["agent_status"] = "idle"  # the fixture's implementor is working: not a quiet spell
        with d.locked_state() as st:
            st["last_change"]["sc-1-a"] = int(now - 3600)
            first = d.heartbeat(s, st, 30, now=now)
            second = d.heartbeat(s, st, 30, now=now + 60)
        self.assertEqual([e["unit"] for e in first], ["sc-1-a"])
        self.assertEqual(second, [])

    def test_no_heartbeat_while_a_worker_is_working(self):
        now, s = time.time(), snap()
        for p in s["panes"]:
            if p.get("tokens", {}).get("role") in d.DEPTH3:
                p["agent_status"] = "working"
        with d.locked_state() as st:
            st["last_change"]["sc-1-a"] = int(now - 3600)
            self.assertEqual(d.heartbeat(s, st, 30, now=now), [])
            self.assertEqual(st["last_change"]["sc-1-a"], int(now))


class LoopTest(Base):
    def test_singleton_and_stop(self):
        fake = os.path.join(self.tmp.name, "herdr")
        with open(fake, "w") as fh:
            fh.write("#!/usr/bin/env python3\nimport json,sys\n"
                     "print(json.dumps({'result': {'snapshot': %r}} if sys.argv[1:3]==['api','snapshot'] else {'result': {}}))\n"
                     % snap())
        os.chmod(fake, 0o755)
        env = dict(os.environ, HERDR_BIN=fake, PROMETHEUS_STATE_DIR=self.tmp.name)
        env.pop("HERDR_WORKSPACE_ID", None)
        cmd = [sys.executable, os.path.join(LIB, "dispatch.py")]
        first = subprocess.Popen(cmd + ["run", "--interval", "1"], env=env, stdout=subprocess.PIPE, text=True)
        for _ in range(50):
            if subprocess.run(cmd + ["status"], env=env, capture_output=True).returncode == 0:
                break
            time.sleep(0.1)
        second = subprocess.run(cmd + ["run", "--interval", "1"], env=env, capture_output=True, text=True)
        self.assertEqual(second.returncode, 3)
        self.assertEqual(subprocess.run(cmd + ["stop"], env=env, capture_output=True).returncode, 0)
        self.assertEqual(first.wait(timeout=10), 0)
        self.assertEqual(subprocess.run(cmd + ["status"], env=env, capture_output=True).returncode, 1)


if __name__ == "__main__":
    unittest.main()
