import os
import subprocess
import sys
import tempfile
import unittest

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import env  # noqa: E402


def run_launch(role, *extra, state_dir):
    e = dict(os.environ, PROMETHEUS_DRY_RUN="1", PROMETHEUS_STATE_DIR=state_dir)
    e.pop("WORKSPACE", None)
    return subprocess.run([os.path.join(LIB, "launch.sh"), role, *extra],
                          capture_output=True, text=True, env=e, cwd=tempfile.gettempdir())


class EnvTest(unittest.TestCase):
    def test_workspace_env_wins(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["WORKSPACE"] = d
            try:
                self.assertEqual(env.workspace_root(), os.path.abspath(d))
            finally:
                del os.environ["WORKSPACE"]

    def test_plugin_checkout_resolves_from_any_cwd(self):
        os.environ.pop("WORKSPACE", None)
        root = env.workspace_root(cwd=tempfile.gettempdir())
        self.assertTrue(os.path.isdir(os.path.join(root, "plugins", "prometheus")))


class LaunchTest(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.state.cleanup()

    def test_role_maps_to_agent(self):
        for role, agent in (("seat", "orchestrator"), ("pm", "project-manager"), ("planner", "planner")):
            out = run_launch(role, state_dir=self.state.name)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn(f"prometheus:{agent}", out.stdout)
            self.assertIn(f"PROMETHEUS_ROLE={role}", out.stdout)
            self.assertNotIn("dontAsk", out.stdout)

    def test_depth_three_is_dont_ask_with_merged_settings(self):
        out = run_launch("implementor", state_dir=self.state.name)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("dontAsk", out.stdout)
        import json
        merged = json.load(open(os.path.join(self.state.name, "settings", "implementor.json")))
        self.assertFalse(merged["enabledPlugins"]["voltus-besstie@brightfield-besstie-local"])
        self.assertIn("AskUserQuestion", merged["permissions"]["deny"])
        self.assertNotIn("$comment", merged)
        rev = run_launch("reviewer", state_dir=self.state.name)
        self.assertEqual(rev.returncode, 0, rev.stderr)
        merged = json.load(open(os.path.join(self.state.name, "settings", "reviewer.json")))
        self.assertIn("Edit(/%s/reviews/**)" % self.state.name, merged["permissions"]["allow"])
        self.assertIn("Bash(git -C * show *)", merged["permissions"]["allow"])

    def test_extra_args_pass_through(self):
        out = run_launch("pm", "--resume", "abc", state_dir=self.state.name)
        self.assertTrue(out.stdout.rstrip().endswith("--resume abc"))

    def test_unknown_role_fails(self):
        self.assertEqual(run_launch("boss", state_dir=self.state.name).returncode, 2)



class OperatorPromptTest(unittest.TestCase):
    def test_only_seat_and_pm_know_the_operator_and_everyone_signs(self):
        with tempfile.TemporaryDirectory() as st:
            for role in ("pm", "seat", "reviewer", "runner"):
                run_launch(role, state_dir=st)
            text = {r: open(os.path.join(st, "settings", r + ".prompt.md")).read() for r in ("pm", "seat", "reviewer", "runner")}
        for r in ("pm", "seat"):
            self.assertIn("## The operator\n", text[r])
            self.assertNotIn("beyond your reach", text[r])
        for r, lead in (("reviewer", "your PM"), ("runner", "the seat")):
            self.assertIn("beyond your reach", text[r])
            self.assertIn("**your lead** — " + lead, text[r])
            self.assertNotIn("GitHub `", text[r])
        for r in text:
            self.assertIn("⚡ Prometheus by instruction of", text[r])
            self.assertNotIn("{", text[r].split("## Signing", 1)[1])


class PluginRepoTest(unittest.TestCase):
    def test_workspace_is_never_the_plugin_repo(self):
        import subprocess
        plugin = os.path.dirname(LIB)
        e = {k: v for k, v in os.environ.items() if k != "WORKSPACE"}
        out = subprocess.run([sys.executable, os.path.join(LIB, "env.py")], cwd=plugin, env=e,
                             capture_output=True, text=True).stdout.strip()
        self.assertNotEqual(os.path.realpath(out), os.path.realpath(plugin))
        self.assertTrue(os.path.isdir(os.path.join(out, "plugins", "prometheus")))


class McpTest(unittest.TestCase):
    def test_roles_get_their_servers_and_writes_are_gated(self):
        import json, stat, tempfile
        with tempfile.TemporaryDirectory() as st:
            for role in ("reviewer", "pm", "seat"):
                run_launch(role, state_dir=st)
            m = {r: json.load(open(os.path.join(st, "mcp", r + ".json")))["mcpServers"] for r in ("reviewer", "pm", "seat")}
            s = {r: json.load(open(os.path.join(st, "settings", r + ".json")))["permissions"] for r in ("reviewer", "pm", "seat")}
            roles = json.load(open(os.path.join(os.path.dirname(LIB), "templates", "mcp", "roles.json")))["roles"]
            for r in ("reviewer", "pm", "seat"):
                self.assertLessEqual(set(m[r]), set(roles[r]))  # never a server the map does not grant
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(st, "mcp", "pm.json")).st_mode), 0o600)
            if "launchdarkly" in m["reviewer"]:
                self.assertIn("mcp__launchdarkly__update-feature-flag", s["reviewer"]["deny"])
                self.assertIn("mcp__launchdarkly__update-feature-flag", s["pm"]["ask"])
                self.assertNotIn("mcp__launchdarkly__update-feature-flag", s["pm"].get("deny", []))
            if "shortcut" in m["seat"]:
                self.assertIn("mcp__shortcut__stories-update", s["seat"]["deny"])
                self.assertNotIn("mcp__shortcut__stories-update", s["pm"].get("deny", []))

if __name__ == "__main__":
    unittest.main()
