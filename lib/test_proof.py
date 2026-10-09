import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
import unittest.mock

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import proof  # noqa: E402


def put(path, text, mode="w"):
    with open(path, mode) as fh:
        fh.write(text)

RUNNER = textwrap.dedent('''
    import os, sys
    from xml.sax.saxutils import quoteattr
    wt, report, tests = sys.argv[1], sys.argv[2], sys.argv[3:]
    code = ""
    for root, _d, files in os.walk(wt):
        if ".git" in root or "/tests" in root:
            continue
        for f in files:
            if f != ".git":
                code += open(os.path.join(root, f)).read()
    cases = []
    for t in tests:
        for line in open(t):
            if ":" not in line or line.startswith("Scenario"):
                continue
            name, rule = [x.strip() for x in line.split(":", 1)]
            if rule == "error":
                body = "<error/>"
            elif rule.startswith("needs ") and rule[6:] not in code:
                body = "<failure/>"
            else:
                body = ""
            cases.append("<testcase classname=%s name=%s>%s</testcase>" % (quoteattr(os.path.basename(t)), quoteattr(name), body))
    open(report, "w").write("<testsuite>%s</testsuite>" % "".join(cases))
''')


class ProofBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state")
        os.environ["PROMETHEUS_STATE_DIR"] = self.state
        self.repo = os.path.join(self.tmp.name, "repo")
        runner = os.path.join(self.tmp.name, "runner.py")
        put(runner, RUNNER)
        self.pkg = {"name": "be", "validate": ["x"], "tests": ["tests/**"], "report": "junit",
                    "scenario_run": "%s %s <worktree> <report> <tests>" % (sys.executable, runner)}
        ent = {"key": "p", "repo": {"root": "repo", "default_branch": "main"}, "packages": [self.pkg]}
        self.patches = [unittest.mock.patch.object(proof.registry, "entry", return_value=ent),
                        unittest.mock.patch.object(proof, "parent", side_effect=self.parent)]
        for p in self.patches:
            p.start()
        self.parents = {}
        self.git("init", "-q", "-b", "main", self.repo, cwd=self.tmp.name)
        self.write("src/app.txt", "")
        self.commit("init")
        self.scen = os.path.join(self.tmp.name, "scenarios.feature")
        put(self.scen, "Scenario: Alpha\n")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()
        os.environ.pop("PROMETHEUS_STATE_DIR", None)

    def parent(self, wt, branch, default):
        return self.parents.get(branch, default)

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, check=True, capture_output=True,
                              text=True, env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                                                  GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")).stdout

    def write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        put(path, text)

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def branch(self, name):
        self.git("checkout", "-q", "-b", name)

    def prove(self):
        return proof.prove("sc-1", self.repo, "p", self.scen)


class ProofTest(ProofBase):
    def build_clean(self):
        self.branch("sc-1-a")
        self.write("tests/test_a.txt", "Scenario: Alpha\nt_alpha: needs ALPHA\n")
        self.commit("tests")
        self.write("src/app.txt", "ALPHA")
        self.commit("code")

    def test_a_clean_rung_proves(self):
        self.build_clean()
        p = self.prove()
        self.assertEqual(p["problems"], [])
        t = p["rungs"][0]["tests"]
        self.assertEqual([(x["red"], x["head"]) for x in t], [("failed", "passed")])
        self.assertEqual([c["kind"] for c in p["rungs"][0]["commits"]], ["tests", "code"])

    def test_a_test_that_already_passes_is_held_before(self):
        self.branch("sc-1-a")
        self.write("src/app.txt", "ALPHA")
        self.commit("code first")
        self.write("tests/test_a.txt", "Scenario: Alpha\nt_alpha: needs ALPHA\n")
        self.commit("tests")
        p = self.prove()
        self.assertEqual(p["problems"], [])
        self.assertEqual(p["held_before"], ["test_a.txt::t_alpha"])

    def test_a_mixed_commit_is_a_problem(self):
        self.branch("sc-1-a")
        self.write("tests/test_a.txt", "Scenario: Alpha\nt_alpha: needs ALPHA\n")
        self.write("src/app.txt", "ALPHA")
        self.commit("both")
        self.assertTrue(any("mixes test and non-test" in x for x in self.prove()["problems"]))

    def test_an_import_error_at_the_tests_commit_is_a_problem(self):
        self.branch("sc-1-a")
        self.write("tests/test_a.txt", "Scenario: Alpha\nt_alpha: error\n")
        self.commit("tests")
        probs = self.prove()["problems"]
        self.assertTrue(any("errors at tests commit" in x for x in probs))

    def test_a_test_red_at_the_head_is_a_problem(self):
        self.branch("sc-1-a")
        self.write("tests/test_a.txt", "Scenario: Alpha\nt_alpha: needs ALPHA\n")
        self.commit("tests")
        self.write("src/app.txt", "NOPE")
        self.commit("code")
        self.assertTrue(any("is failed at the head" in x for x in self.prove()["problems"]))

    def test_a_scenario_without_a_test_and_a_missing_failure_mode_test(self):
        self.build_clean()
        put(self.scen, "Scenario Outline: Beta\n", "a")
        d = proof.story_dir("sc-1")
        os.makedirs(d, exist_ok=True)
        put(os.path.join(d, "failure-modes.md"), 
            "| Mode | Where today | Test | Rung |\n|---|---|---|---|\n"
            "| empty | a.py:1 | t_alpha | be |\n| gone | b.py:2 | t_missing | be |\n"
            "| sign | c.py:3 | cannot happen: importer rejects it | — |\n")
        probs = self.prove()["problems"]
        self.assertIn('scenario "Beta" has no test carrying its Scenario: line', probs)
        self.assertIn('failure mode "gone": test "t_missing" not found', probs)
        self.assertEqual(len(probs), 2)

    def test_two_rungs_are_walked_bottom_first(self):
        self.build_clean()
        self.branch("sc-1-a-fe")
        self.parents["sc-1-a-fe"] = "sc-1-a"
        self.write("tests/test_b.txt", "t_beta: needs BETA\n")
        self.commit("tests fe")
        self.write("src/fe.txt", "BETA")
        self.commit("code fe")
        p = self.prove()
        self.assertEqual([r["branch"] for r in p["rungs"]], ["sc-1-a", "sc-1-a-fe"])
        self.assertEqual(p["problems"], [])

    def test_a_proof_goes_stale_when_a_branch_moves(self):
        self.build_clean()
        p = self.prove()
        self.assertEqual(proof.current(p, self.repo), [])
        self.write("src/app.txt", "ALPHA2")
        self.commit("more")
        self.assertTrue(any("moved since the proof" in x for x in proof.current(p, self.repo)))


class GlobTest(unittest.TestCase):
    def test_double_star_spans_directories_and_single_does_not(self):
        self.assertTrue(proof.glob_re("js/app/**/*.test.ts").match("js/app/a/b/x.test.ts"))
        self.assertTrue(proof.glob_re("js/app/**/*.test.ts").match("js/app/x.test.ts"))
        self.assertFalse(proof.glob_re("js/app/*.test.ts").match("js/app/a/x.test.ts"))
        self.assertTrue(proof.glob_re("py/tests/**").match("py/tests/a/conftest.py"))


class ParseTest(unittest.TestCase):
    def test_jest_suite_error_and_assertions(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write('{"testResults": [{"name": "/w/a.test.ts", "status": "failed", "assertionResults": [],'
                     ' "failureMessage": "Cannot find module"}, {"name": "/w/b.test.ts", "status": "failed",'
                     ' "assertionResults": [{"fullName": "b works", "status": "failed"},'
                     ' {"fullName": "b old", "status": "passed"}]}]}')
        try:
            self.assertEqual(proof.parse(fh.name, "jest-json"),
                             {"/w/a.test.ts::<suite>": "error", "/w/b.test.ts::b works": "failed",
                              "/w/b.test.ts::b old": "passed"})
        finally:
            os.unlink(fh.name)


if __name__ == "__main__":
    unittest.main()
