import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import registry  # noqa: E402
import migrate_team_json  # noqa: E402

GUARD = os.path.join(os.path.dirname(LIB), "hooks", "project-guard.py")

WORKSPACE = {"operator": {"name": "Op"}, "trackers": {
    "shortcut": {"kind": "shortcut", "workflow": {"id": "1", "intake": "backlog", "states": [{"key": "backlog", "id": "1", "name": "Backlog"}]}},
    "operator": {"kind": "operator"}}}
PROJECTS = {
    "alpha": {"key": "alpha", "description": "a", "access": "editable", "repo": {"root": "repos/alpha", "slug": "org/alpha"},
              "owned_paths": ["src/alpha", "py/alpha"], "vcs": {"tool": "graphite"}, "tracker": {"ref": "shortcut"}},
    "beta": {"key": "beta", "description": "b", "access": "editable", "repo": {"root": "repos/beta", "slug": "org/beta"},
             "vcs": {"tool": "git"}, "tracker": {"ref": "shortcut"}},
    "nested": {"key": "nested", "description": "n", "access": "editable", "repo": {"root": "repos/beta/sub"}},
    "workspace": {"key": "workspace", "description": "w", "access": "editable", "repo": {"root": "."},
                  "owned_paths": ["plugins", "docs"], "vcs": {"tool": "git-local"}, "tracker": {"ref": "operator"}},
    "refclone": {"key": "refclone", "description": "r", "access": "reference", "repo": {"root": "samples/refclone", "pin": "origin/main"}},
}


class Base(unittest.TestCase):
    def setUp(self):
        self.ws = os.path.realpath(tempfile.mkdtemp())
        self.state = tempfile.mkdtemp()
        os.environ.update(WORKSPACE=self.ws, PROMETHEUS_STATE_DIR=self.state)
        for k in ("PROMETHEUS_PROJECT", "HERDR_ENV", "HERDR_WORKSPACE_ID", "CLAUDE_SESSION_ID"):
            os.environ.pop(k, None)
        self.write(WORKSPACE, PROJECTS)

    def tearDown(self):
        shutil.rmtree(self.ws)
        shutil.rmtree(self.state)
        registry._cache.clear()

    def write(self, ws, projects, local=None):
        d = os.path.join(self.ws, ".claude", "prometheus")
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(os.path.join(d, "projects"))
        json.dump(ws, open(os.path.join(d, "workspace.json"), "w"))
        for k, v in projects.items():
            json.dump(v, open(os.path.join(d, "projects", k + ".json"), "w"))
        if local is not None:
            json.dump(local, open(os.path.join(d, "local.json"), "w"))
        registry._cache.clear()

    def p(self, rel):
        return os.path.join(self.ws, rel)


class LookupTest(Base):
    def test_projects_entry_field(self):
        self.assertEqual(sorted(registry.projects()), sorted(PROJECTS))
        self.assertEqual(registry.field("repo.slug", key="alpha"), "org/alpha")
        self.assertEqual(registry.field("nope.x", key="alpha", default="d"), "d")

    def test_local_overrides_merge(self):
        self.write(WORKSPACE, PROJECTS, {"projects": {"alpha": {"repo": {"default_branch": "dev"}}}})
        self.assertEqual(registry.entry("alpha")["repo"], {"root": "repos/alpha", "slug": "org/alpha", "default_branch": "dev"})

    def test_unreadable_is_none_not_empty(self):
        open(self.p(".claude/prometheus/projects/alpha.json"), "w").write("{nope")
        registry._cache.clear()
        self.assertIsNone(registry.projects())
        shutil.rmtree(self.p(".claude/prometheus"))
        self.assertIsNone(registry.projects())

    def test_repos_and_repo_projects_editable_only(self):
        self.assertEqual(registry.repos(), ["org/alpha", "org/beta"])
        self.assertEqual(registry.repo_projects(), {"org/alpha": "alpha", "org/beta": "beta"})

    def test_tracker_and_runbook(self):
        self.assertEqual(registry.tracker("alpha")["kind"], "shortcut")
        self.assertEqual(registry.tracker("workspace")["kind"], "operator")
        self.assertIsNone(registry.runbook("alpha", "deploy.md"))


class OwnerTest(Base):
    def test_matrix(self):
        self.assertEqual(registry.owner(self.p("repos/alpha/src/alpha/x.ts"))[::2], ("alpha", "src/alpha/x.ts"))
        self.assertEqual(registry.owner(self.p("repos/alpha/other/x.ts"))[0], "alpha")
        self.assertEqual(registry.owner(self.p("samples/refclone/a.py"))[0], "refclone")
        self.assertIsNone(registry.owner(self.p("repos/unknown/a.py"))[0])
        self.assertIsNone(registry.owner(self.p("docs/x.md"))[0])

    def test_longest_root_wins(self):
        self.assertEqual(registry.owner(self.p("repos/beta/sub/a.py"))[0], "nested")
        self.assertEqual(registry.owner(self.p("repos/beta/a.py"))[0], "beta")

    def test_worktree_resolves_through_its_checkout(self):
        repo = self.p("repos/alpha")
        os.makedirs(repo)
        subprocess.run(["git", "init", "-q", repo], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "--allow-empty", "-m", "i"], check=True,
                       env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))
        wt = self.p(".worktrees/feat")
        subprocess.run(["git", "-C", repo, "worktree", "add", "-q", wt], check=True)
        self.assertEqual(registry.owner(os.path.join(wt, "src/alpha/x.ts"))[::2], ("alpha", "src/alpha/x.ts"))


class ActiveTest(Base):
    def test_order_and_no_default(self):
        self.assertEqual(registry.active(cwd=self.p("repos/beta"))[0], "beta")
        self.assertEqual(registry.active(cwd=self.ws), (None, None))
        os.makedirs(os.path.dirname(registry.pin_path("s1")))
        json.dump({"project": "alpha"}, open(registry.pin_path("s1"), "w"))
        self.assertEqual(registry.active(cwd=self.p("repos/beta"), session_id="s1")[0], "alpha")
        os.environ["PROMETHEUS_PROJECT"] = "beta"
        self.assertEqual(registry.active(cwd=self.ws, session_id="s1")[0], "beta")
        os.environ["PROMETHEUS_PROJECT"] = "nope"
        self.assertEqual(registry.active(cwd=self.p("repos/beta"))[0], "beta")

    def test_unit_token_rung(self):
        world = os.path.join(self.state, "world.json")
        json.dump({"workspaces": [{"workspace_id": "w1", "tokens": {"unit": "u", "project": "beta"}}]}, open(world, "w"))
        os.environ.update(HERDR_ENV="1", HERDR_WORKSPACE_ID="w1", FAKE_HERDR_WORLD=world,
                          HERDR_BIN=os.path.join(LIB, "testing", "fake_herdr.py"))
        try:
            self.assertEqual(registry.active(cwd=self.ws)[0], "beta")
        finally:
            for k in ("HERDR_BIN", "FAKE_HERDR_WORLD"):
                os.environ.pop(k)

    def test_repo_project_includes_workspace_root(self):
        self.assertEqual(registry.repo_project(cwd=self.ws)[0], "workspace")
        self.assertEqual(registry.repo_project(cwd=self.p("docs"))[0], "workspace")
        self.assertEqual(registry.repo_project(cwd=self.p("repos/alpha"))[0], "alpha")
        self.assertEqual(registry.repo_project(cwd="/")[0], None)


class CheckTest(Base):
    def test_clean_and_dirty(self):
        self.assertEqual(registry.check(), [])
        bad = dict(PROJECTS, alpha=dict(PROJECTS["alpha"], acces="editable", tracker={"ref": "jira"}))
        self.write(WORKSPACE, bad)
        errs = registry.check()
        self.assertTrue(any("unknown field 'acces'" in e for e in errs))
        self.assertTrue(any("tracker.ref 'jira'" in e for e in errs))

    def test_duplicate_root_and_missing_runbook(self):
        bad = dict(PROJECTS, gamma=dict(PROJECTS["beta"], key="gamma", runbooks=["deploy.md"]))
        self.write(WORKSPACE, bad)
        errs = registry.check()
        self.assertTrue(any("also claimed" in e for e in errs))
        self.assertTrue(any("runbook deploy.md missing" in e for e in errs))


class GuardTest(Base):
    def run_guard(self, rel, sid="s1", tool="Edit"):
        payload = {"hook_event_name": "PreToolUse", "session_id": sid, "cwd": self.ws, "tool_name": tool,
                   "tool_input": {"file_path": rel}}
        return subprocess.run([sys.executable, GUARD], input=json.dumps(payload), capture_output=True, text=True,
                              env=dict(os.environ))

    def test_matrix(self):
        self.assertEqual(self.run_guard("docs/x.md").returncode, 0)
        self.assertEqual(self.run_guard("samples/refclone/x.py").returncode, 2)
        self.assertEqual(self.run_guard("repos/unknown/x.py").returncode, 2)
        out = self.run_guard("repos/alpha/other/x.py")
        self.assertEqual(out.returncode, 2)
        self.assertIn("owned paths", out.stderr)
        self.assertEqual(self.run_guard("repos/alpha/src/alpha/x.ts").returncode, 0)
        cross = self.run_guard("repos/beta/x.py")
        self.assertEqual(cross.returncode, 2)
        self.assertIn("Cross-project", cross.stderr)
        self.assertEqual(self.run_guard("repos/beta/x.py", sid="s2").returncode, 0)

    def test_unreadable_registry_fails_closed_for_projects_only(self):
        shutil.rmtree(self.p(".claude/prometheus"))
        self.assertEqual(self.run_guard("repos/alpha/src/alpha/x.ts").returncode, 2)
        self.assertEqual(self.run_guard("docs/x.md").returncode, 0)

    def test_session_start_announces(self):
        payload = {"hook_event_name": "SessionStart", "session_id": "s9", "cwd": self.ws}
        out = subprocess.run([sys.executable, GUARD], input=json.dumps(payload), capture_output=True, text=True)
        ctx = json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("none yet", ctx)
        self.assertNotIn("Registry check failed", ctx)


class MigrationTest(Base):
    def test_team_json_maps_clean(self):
        src = os.path.join(self.ws, ".claude", "voltus-besstie")
        os.makedirs(os.path.join(src, "projects", "alpha"))
        open(os.path.join(src, "projects", "alpha", "deploy.md"), "w").write("# deploy")
        team = {"_comment": "c", "shortcut": {"org_slug": "o"}, "operator": {"name": "Op", "_c": "x"},
                "default_project": "alpha", "team": {"name": "T", "team_id": "t1"},
                "workflow": {"id": "1", "name": "D", "intake_state": {"id": "1"}, "states": [
                    {"name": "Backlog State", "id": "1"}, {"name": "In Development", "id": "2"},
                    {"name": "Ready for Deploy", "id": "3", "gate": "RETIRED 2026"}]},
                "labels": ["spike"], "epics": {"default_catch_all": {"id": "9", "name": "E"}}, "docs": {"folder": None},
                "projects": {"_comment": "x",
                             "alpha": {"description": "A", "repo": "org/alpha", "root": "repos/alpha", "access": "editable",
                                       "vcs": "graphite", "pr_title_prefix": "alpha:", "tracker": {"mode": "shortcut", "team_id": "t1"},
                                       "deploy": "thor — see deploy.md", "migrations": "alembic — db/versions",
                                       "validation": {"_comment": "why", "fe": {"path": "js", "commands": ["npm t"], "_note": "trap"}},
                                       "test_db": "x_test", "specs": "docs/specs/alpha/"},
                             "ref": {"description": "R", "root": "samples/ref", "access": "reference"}}}
        json.dump(team, open(os.path.join(src, "team.json"), "w"))
        p = migrate_team_json.plan(self.ws)
        self.assertEqual(migrate_team_json.validate(p), [])
        alpha = json.loads(p["files"]["projects/alpha.json"])
        self.assertEqual(alpha["deploy"], {"tool": "thor", "runbook": "deploy.md"})
        self.assertEqual(alpha["migrations"], {"tool": "alembic", "path": "db/versions"})
        self.assertEqual(alpha["packages"], [{"name": "fe", "validate": ["npm t"], "path": "js", "runbook": "registry-notes.md"}])
        self.assertEqual(alpha["extra"], {"test_db": "x_test"})
        notes = p["files"]["projects/alpha/registry-notes.md"]
        self.assertIn("trap", notes)
        self.assertIn("thor — see deploy.md", notes)
        ws = json.loads(p["files"]["workspace.json"])
        self.assertEqual([s["key"] for s in ws["trackers"]["shortcut"]["workflow"]["states"]], ["backlog_state", "in_development"])
        self.assertTrue(any("default_project" in w for w in p["warnings"]))
        self.assertNotIn("_c", ws["operator"])


if __name__ == "__main__":
    unittest.main()


class PlanningFieldTest(unittest.TestCase):
    def test_planning_and_request_from_validate(self):
        import json
        import schema_lite
        schema = json.load(open(registry.SCHEMA))
        base = {"key": "p", "description": "d", "access": "editable", "repo": {"root": "repos/p"}}
        ok = dict(base, planning={"repo": "voltusdev/voltus-vantage-planning", "team_dir": "teams/b-team"},
                  review={"request_from": ["voltusdev/team-brightfield"]})
        self.assertEqual(schema_lite.validate(ok, {"$ref": "#/$defs/project"}, schema), [])
        bad = dict(base, planning={"repo": "voltusdev/voltus-vantage-planning"})
        self.assertTrue(schema_lite.validate(bad, {"$ref": "#/$defs/project"}, schema))


class ScenarioRunFieldTest(unittest.TestCase):
    def test_package_proof_fields_validate(self):
        import json
        import schema_lite
        schema = json.load(open(registry.SCHEMA))
        pkg = {"name": "be", "validate": ["make test"], "tests": ["py/tests/**"],
               "scenario_run": "run <worktree> <tests> --out=<report>", "report": "junit"}
        base = {"key": "p", "description": "d", "access": "editable", "repo": {"root": "repos/p"}}
        self.assertEqual(schema_lite.validate(dict(base, packages=[pkg]), {"$ref": "#/$defs/project"}, schema), [])
        for bad in ({"report": "tap"}, {"scenario_run": "run everything"}):
            self.assertTrue(schema_lite.validate(dict(base, packages=[dict(pkg, **bad)]),
                                                 {"$ref": "#/$defs/project"}, schema))
