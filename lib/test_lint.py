import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import lint  # noqa: E402

HEADER = "#!/bin/zsh\n# ---\n# name: %s\n# description: d\n# usage: %s.sh\n# ---\n"
PY_HEADER = "#!/usr/bin/env python3\n# ---\n# name: %s\n# description: d\n# usage: %s.py\n# ---\n"
WORKSPACE = {"operator": {"name": "Op"}, "trackers": {"operator": {"kind": "operator"}}}
PROJECT = {"key": "alpha", "description": "a", "access": "editable", "repo": {"root": "repos/alpha"},
           "tracker": {"ref": "operator"}, "runbooks": ["deploy.md"]}
ROLES = {"roles": {"seat": ["shortcut"], "pm": ["shortcut"], "reviewer": []}, "writers": {"shortcut": ["pm"]}}


class Base(unittest.TestCase):
    def setUp(self):
        self.ws = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ws)
        self.plugin = os.path.join(self.ws, "plugins", "prometheus")
        self.write("agents/reviewer.md", "---\nname: reviewer\ndescription: r\n---\nBody.\n")
        self.write("agents/orchestrator.md", "---\nname: orchestrator\ndescription: o\n---\nBody.\n")
        self.write("agents/project-manager.md", "---\nname: project-manager\ndescription: p\n---\nBody.\n")
        self.write("skills/review/SKILL.md",
                   "---\nname: review\ndescription: r\n---\nSee references/findings.md and `send.sh`.\n")
        self.write("skills/review/references/findings.md", "Findings.\n")
        self.write("skills/dispatch/SKILL.md", "---\nname: dispatch\ndescription: d\n---\nBody.\n")
        self.write("skills/dispatch/scripts/send.sh", HEADER % ("send", "send"), exe=True)
        self.write("commands/begin.md", "---\ndescription: start\n---\nRun it.\n")
        self.write("lib/tool.py", PY_HEADER % ("tool", "tool"))
        self.write("lib/launch.sh", HEADER % ("launch", "launch"), exe=True)
        self.write("lib/test_tool.py", "import unittest\n")
        self.write("templates/settings/reviewer.json", json.dumps(
            {"permissions": {"allow": ["Read", "Bash(git diff *)", "Edit(/{state_dir}/reviews/**)",
                                       "Edit(//abs/path/**)"], "deny": ["AskUserQuestion"]}}))
        self.write("templates/settings/launch.json", json.dumps(
            {"$comment": "disables voltus-besstie", "enabledPlugins": {"voltus-besstie@x": False}}))
        self.write("templates/mcp/roles.json", json.dumps(ROLES))
        self.ws_write(".claude/prometheus/workspace.json", json.dumps(WORKSPACE))
        self.ws_write(".claude/prometheus/projects/alpha.json", json.dumps(PROJECT))
        self.ws_write(".claude/prometheus/projects/alpha/deploy.md", "Deploy.\n")
        self.ctx = lint.Ctx(self.plugin, self.ws)

    def write(self, rel, text, exe=False):
        self._put(os.path.join(self.plugin, rel), text, exe)

    def ws_write(self, rel, text):
        self._put(os.path.join(self.ws, rel), text, False)

    def _put(self, path, text, exe):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IXUSR if exe else mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))

    def errors(self, check):
        return [f for f in lint.RUNNERS[check](self.ctx) if f["severity"] == "error"]

    def messages(self, check):
        return [f["message"] for f in lint.RUNNERS[check](self.ctx)]


class TestClean(Base):
    def test_fixture_is_clean(self):
        self.assertEqual(lint.run(self.ctx), [])

    def test_main_exit_codes(self):
        argv = ["--plugin", self.plugin, "--workspace", self.ws]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(lint.main(argv), 0)
        self.write("agents/bad.md", "no frontmatter\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(lint.main(argv + ["--json", "--only", "frontmatter"]), 1)
        found = json.loads(buf.getvalue())
        self.assertEqual({tuple(sorted(f)) for f in found}, {("check", "file", "line", "message", "severity")})

    def test_warnings_do_not_fail(self):
        rule = "Every later message to an agent goes through the send script and never through raw typing in a tab."
        self.write("agents/reviewer.md", "---\nname: reviewer\ndescription: r\n---\n%s\n" % rule)
        self.write("skills/dispatch/SKILL.md", "---\nname: dispatch\ndescription: d\n---\n%s\n" % rule)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(lint.main(["--plugin", self.plugin, "--workspace", self.ws, "--only", "duplicates"]), 0)


class TestFrontmatter(Base):
    def test_missing_block(self):
        self.write("agents/runner.md", "Just text.\n")
        self.assertIn("no frontmatter block (--- ... ---)", self.messages("frontmatter"))

    def test_agent_name_mismatch(self):
        self.write("agents/runner.md", "---\nname: walker\ndescription: r\n---\n")
        self.assertTrue(any("does not match its file stem" in m for m in self.messages("frontmatter")))

    def test_skill_name_mismatch_and_missing_description(self):
        self.write("skills/data/SKILL.md", "---\nname: datum\n---\n")
        msgs = self.messages("frontmatter")
        self.assertTrue(any("does not match its dir" in m for m in msgs))
        self.assertIn("frontmatter has no description", msgs)

    def test_command_needs_description_not_name(self):
        self.write("commands/stop.md", "---\nallowed-tools: Bash\n---\n")
        self.assertEqual(self.messages("frontmatter"), ["frontmatter has no description"])

    def test_skill_dir_without_skill_md(self):
        self.write("skills/empty/references/x.md", "x\n")
        self.assertIn("skill dir has no SKILL.md", self.messages("frontmatter"))


class TestHeaders(Base):
    def test_missing_header(self):
        self.write("lib/bare.py", "import os\n")
        self.assertIn("no '# ---' header block", self.messages("headers"))

    def test_missing_usage(self):
        self.write("skills/dispatch/scripts/stop.sh", "#!/bin/zsh\n# ---\n# name: stop\n# description: d\n# ---\n",
                   exe=True)
        self.assertEqual(self.messages("headers"), ["header has no usage"])

    def test_not_executable(self):
        self.write("skills/dispatch/scripts/stop.sh", HEADER % ("stop", "stop"))
        self.assertEqual(self.messages("headers"), ["script is not executable"])

    def test_tests_and_testing_skipped(self):
        self.write("lib/test_other.py", "import os\n")
        self.write("lib/testing/fake.py", "import os\n")
        self.assertEqual(self.messages("headers"), [])


class TestPaths(Base):
    def test_missing_plugin_path(self):
        self.write("agents/reviewer.md", "---\nname: reviewer\ndescription: r\n---\nRun `lib/gone.py`.\n")
        errs = self.errors("paths")
        self.assertEqual([(e["file"], e["line"]) for e in errs], [("agents/reviewer.md", 5)])

    def test_plugin_root_and_placeholders(self):
        self.write("agents/reviewer.md", "---\nname: reviewer\ndescription: r\n---\n"
                   "`$CLAUDE_PLUGIN_ROOT/skills/dispatch/scripts/send.sh`, `templates/settings/<role>.json`,"
                   " `Bash(*/skills/dispatch/scripts/send.sh *)`, plugins/prometheus/lib/launch.sh.\n"
                   "Foreign repo path repos/x/lib/thing.py is not ours.\n")
        self.assertEqual(self.errors("paths"), [])
        self.write("commands/begin.md", "---\ndescription: s\n---\n${CLAUDE_PLUGIN_ROOT}/skills/dispatch/scripts/nope.sh\n")
        self.assertEqual(len(self.errors("paths")), 1)

    def test_references_resolve_to_own_skill(self):
        self.write("skills/dispatch/SKILL.md", "---\nname: dispatch\ndescription: d\n---\nreferences/findings.md\n")
        self.assertEqual(len(self.errors("paths")), 1)
        self.write("skills/dispatch/SKILL.md",
                   "---\nname: dispatch\ndescription: d\n---\n`review` → references/findings.md\n")
        self.assertEqual(self.errors("paths"), [])

    def test_references_from_agent_match_any_skill(self):
        self.write("agents/reviewer.md", "---\nname: reviewer\ndescription: r\n---\nreferences/findings.md, references/gone.md\n")
        self.assertEqual([e["message"] for e in self.errors("paths")], ["references/gone.md not found under any skill"])

    def test_component_refs(self):
        self.write("agents/reviewer.md", "---\nname: reviewer\ndescription: r\n---\n"
                   "prometheus:review prometheus:orchestrator prometheus:begin prometheus:nothing\n")
        self.assertEqual([e["message"] for e in self.errors("paths")],
                         ["prometheus:nothing is not a skill, agent or command"])

    def test_bare_script_names(self):
        self.write("agents/reviewer.md", "---\nname: reviewer\ndescription: r\n---\n"
                   "`send.sh`, `launch.sh`, `deploy-it.sh`, `scratch.sh`\n")
        self.ws_write(".claude/prometheus/projects/alpha/scratch.sh", "")
        self.assertEqual([e["message"] for e in self.errors("paths")],
                         ["script deploy-it.sh exists nowhere in the plugin or the registry"])

    def test_registry_paths(self):
        self.write("agents/reviewer.md", "---\nname: reviewer\ndescription: r\n---\n"
                   ".claude/prometheus/projects/alpha/deploy.md .claude/prometheus/projects/<key>/ "
                   ".claude/prometheus/local.json .claude/prometheus/projects/*/*.md "
                   ".claude/prometheus/projects/alpha/gone.md\n")
        self.assertEqual([e["message"] for e in self.errors("paths")],
                         ["registry path .claude/prometheus/projects/alpha/gone.md does not exist in the workspace"])


class TestSettings(Base):
    def test_bad_json(self):
        self.write("templates/settings/runner.json", "{nope")
        self.assertTrue(any(m.startswith("invalid JSON") for m in self.messages("settings")))

    def test_write_rule_and_single_slash(self):
        self.write("templates/settings/reviewer.json", json.dumps({"permissions": {"allow": [
            "Write(/{state_dir}/x/**)", "Edit(/Users/me/x/**)", "Edit(/{workspace}/**)", "Edit(src/**)"]}}))
        msgs = self.messages("settings")
        self.assertEqual(len(msgs), 2)
        self.assertIn("never match", msgs[0])
        self.assertIn("needs //", msgs[1])

    def test_rule_shape(self):
        self.write("templates/settings/reviewer.json", json.dumps({"permissions": {"deny": ["Bash(", 3, "mcp__x__y-z"]}}))
        self.assertEqual(len(self.messages("settings")), 2)

    def test_roles_map_to_agents(self):
        roles = dict(ROLES, ask_writers={"x": ["ghost"]})
        self.write("templates/mcp/roles.json", json.dumps(roles))
        self.write("templates/settings/phantom.json", json.dumps({"permissions": {}}))
        msgs = self.messages("settings")
        self.assertIn("role 'ghost' maps to no agent (nor the seat)", msgs)
        self.assertIn("settings for role 'phantom', which maps to no agent", msgs)


class TestStale(Base):
    def test_flags_old_names(self):
        self.write("skills/dispatch/SKILL.md", "---\nname: dispatch\ndescription: d\n---\n"
                   "Read team.json and docs/vault/x.md; state in ~/.claude/prometheus.\n")
        self.assertEqual(len(self.errors("stale")), 3)

    def test_plugin_root_variable_in_a_command(self):
        self.write("skills/dispatch/SKILL.md", "---\nname: dispatch\ndescription: d\n---\n"
                   "`python3 \"$CLAUDE_PLUGIN_ROOT/lib/tool.py\"`, `${CLAUDE_PLUGIN_ROOT}/lib/tool.py`; "
                   "scripts in $CLAUDE_PLUGIN_ROOT/skills/dispatch/scripts/; `python3 <plugin>/lib/tool.py`.\n")
        self.assertEqual(len(self.errors("stale")), 2)
        self.assertEqual(self.errors("paths"), [])

    def test_allowlist(self):
        self.assertTrue(lint.allowlisted("templates/settings/launch.json"))
        self.assertTrue(lint.allowlisted("lib/test_registry.py"))
        self.assertFalse(lint.allowlisted("templates/settings/reviewer.json"))
        self.assertEqual(self.errors("stale"), [])


class TestDuplicates(Base):
    RULE = "Every later message to an agent goes through the send script and never through raw typing in a tab."

    def test_cross_file_duplicate(self):
        self.write("agents/reviewer.md", "---\nname: reviewer\ndescription: r\n---\nIntro.\n\n%s\n" % self.RULE)
        self.write("skills/dispatch/SKILL.md", "---\nname: dispatch\ndescription: d\n---\n%s\n" % self.RULE.upper())
        found = lint.check_duplicates(self.ctx)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0]["severity"], found[0]["file"], found[0]["line"]), ("warning", "agents/reviewer.md", 7))

    def test_same_file_short_and_different_ignored(self):
        self.write("agents/reviewer.md", "---\nname: reviewer\ndescription: r\n---\n%s\n%s\n" % (self.RULE, self.RULE))
        self.write("skills/dispatch/SKILL.md", "---\nname: dispatch\ndescription: d\n---\n"
                   "Short rule here.\nThe reviewer posts a single closing review whose event follows from the counts alone.\n")
        self.write("templates/brief.md", self.RULE + "\n")
        self.assertEqual(lint.check_duplicates(self.ctx), [])


class TestRegistry(Base):
    def test_sound(self):
        self.assertEqual(lint.check_registry(self.ctx), [])

    def test_missing_runbook(self):
        os.remove(os.path.join(self.ws, ".claude/prometheus/projects/alpha/deploy.md"))
        errs = lint.check_registry(self.ctx)
        self.assertEqual(len(errs), 1)
        self.assertIn("runbook deploy.md missing", errs[0]["message"])
        self.assertEqual(errs[0]["file"], ".claude/prometheus/projects/alpha.json")

    def test_no_workspace_is_a_warning(self):
        found = lint.check_registry(lint.Ctx(self.plugin, None))
        self.assertEqual([f["severity"] for f in found], ["warning"])


if __name__ == "__main__":
    unittest.main()
