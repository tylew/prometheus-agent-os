import importlib.util
import os
import subprocess
import tempfile
import unittest
import unittest.mock

HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "builder-guard.py")
spec = importlib.util.spec_from_file_location("builder_guard", HOOK)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class BuilderGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wt = os.path.join(self.tmp.name, "wt")
        os.makedirs(os.path.join(self.wt, "py", "tests"))
        open(os.path.join(self.wt, ".git"), "w").close()
        self.p = unittest.mock.patch.object(guard, "test_globs", return_value=["py/tests/**", "js/**/*.test.ts"])
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def edit(self, rel, agent="prometheus:builder"):
        return guard.check({"agent_type": agent, "tool_name": "Edit",
                            "tool_input": {"file_path": os.path.join(self.wt, rel)}})

    def bash(self, cmd, agent="prometheus:builder"):
        return guard.check({"agent_type": agent, "tool_name": "Bash", "tool_input": {"command": cmd}})

    def test_builder_cannot_edit_tests_or_story_files(self):
        self.assertIn("test file", self.edit("py/tests/test_a.py"))
        self.assertIn("test file", self.edit("js/app/x.test.ts"))
        self.assertIsNone(self.edit("py/app/a.py"))
        self.assertIn("idr.md", guard.check({"agent_type": "prometheus:builder", "tool_name": "Write",
                                             "tool_input": {"file_path": "/s/engine/stories/sc-1/idr.md"}}))

    def test_other_agents_pass(self):
        self.assertIsNone(self.edit("py/tests/test_a.py", agent="prometheus:implementor"))
        self.assertIsNone(self.edit("py/tests/test_a.py", agent=None))
        self.assertIsNone(self.bash("git commit -m x", agent=None))

    def test_builder_git_reads_only(self):
        self.assertIsNone(self.bash("git -C /wt diff --stat && git status"))
        self.assertIn("git commit", self.bash("make lint && git commit -m x"))
        self.assertIn("gt modify", self.bash("gt modify -c -m x"))
        self.assertIn("git add", self.bash("FOO=1 git -C /wt add a.py"))
        self.assertIsNone(self.bash("npm --prefix /wt/js run test brightfield-besstie"))

    def test_the_hook_exits_2_with_the_reason(self):
        import json
        out = subprocess.run(["python3", HOOK], input=json.dumps({"agent_type": "prometheus:builder", "tool_name": "Bash",
                                                                  "tool_input": {"command": "git push"}}),
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)
        self.assertIn("git push", out.stderr)


if __name__ == "__main__":
    unittest.main()
