import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import dispatch as d  # noqa: E402


def snap(**over):
    s = {
        "workspaces": [
            {"workspace_id": "wC", "label": "control", "tokens": {"dispatcher": "running"}},
            {"workspace_id": "wA", "label": "sc-1-a", "tokens": {"unit": "sc-1-a", "kind": "story", "stories": "sc-1", "prs": "o/r#10,o/r#11"}},
            {"workspace_id": "wB", "label": "plan-x", "tokens": {"unit": "plan-x", "kind": "planning", "stories": "sc-2"}},
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

    def test_planning_unit_routes_lead_to_planner(self):
        self.assertEqual(d.route(snap(), {"story": "sc-2"}), "wB:p1")

    def test_seat_and_role_within_unit(self):
        s = snap()
        self.assertEqual(d.route(s, {"role": "seat"}), "wC:p1")
        self.assertEqual(d.route(s, {"unit": "sc-1-a", "role": "implementor", "item": "derate"}), "wA:p2")

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
        now = time.time()
        with d.locked_state() as st:
            st["last_change"]["sc-1-a"] = int(now - 3600)
            first = d.heartbeat(snap(), st, 30, now=now)
            second = d.heartbeat(snap(), st, 30, now=now + 60)
        self.assertEqual([e["unit"] for e in first], ["sc-1-a"])
        self.assertEqual(second, [])


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
