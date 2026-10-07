import os
import sys
import unittest

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import probes  # noqa: E402


def bash(cmd):
    return {"kind": "bash", "cmd": cmd, "tool": "Bash", "arg": cmd, "live": None}


def tool(name, arg=None):
    return {"kind": "tool", "cmd": name, "tool": name, "arg": arg, "live": False}


class SplitTest(unittest.TestCase):
    def test_operators(self):
        self.assertEqual(probes.split_compound("a && b || c; d | e & f\ng"), list("abcdefg"))

    def test_quotes_protect_operators(self):
        self.assertEqual(probes.split_compound("send.sh --role pm \"a && b; c\""), ['send.sh --role pm "a && b; c"'])
        self.assertEqual(probes.split_compound("echo 'x | y'"), ["echo 'x | y'"])

    def test_redirection_is_not_a_separator(self):
        self.assertEqual(probes.split_compound("make lint 2>&1"), ["make lint 2>&1"])

    def test_substitution_is_unparsed(self):
        self.assertIsNone(probes.split_compound("ls $(pwd)"))
        self.assertIsNone(probes.split_compound("echo \"`id`\""))
        self.assertIsNone(probes.split_compound("(cd x; ls)"))
        self.assertIsNone(probes.split_compound("echo 'open"))


class BashPatternTest(unittest.TestCase):
    def test_prefix_with_space_star(self):
        m = probes.bash_pattern_matches
        self.assertTrue(m("ls *", "ls -la"))
        self.assertTrue(m("ls *", "ls"))
        self.assertFalse(m("ls *", "lsof"))
        self.assertTrue(m("ls*", "lsof"))

    def test_exact_and_legacy(self):
        m = probes.bash_pattern_matches
        self.assertTrue(m("git status", "git status"))
        self.assertFalse(m("git status", "git status --short"))
        self.assertTrue(m("npm run test:*", "npm run test --watch"))
        self.assertTrue(m(None, "anything"))
        self.assertTrue(m("*", "anything"))

    def test_inner_wildcards(self):
        m = probes.bash_pattern_matches
        self.assertTrue(m("git -C * show *", "git -C /w/x show HEAD"))
        self.assertTrue(m("gh api repos/*/compare/*", "gh api repos/o/r/compare/a...b"))
        self.assertTrue(m("*/skills/dispatch/scripts/send.sh *", "/p/skills/dispatch/scripts/send.sh --role pm x"))

    def test_quoted_path_needs_the_quoted_rule(self):
        cmd = 'python3 "/p/lib/registry.py" field repo.slug --key besstie'
        self.assertFalse(probes.bash_pattern_matches("python3 */lib/registry.py *", cmd))
        self.assertTrue(probes.bash_pattern_matches('python3 "*/lib/registry.py" *', cmd))


class DecideTest(unittest.TestCase):
    perms = {"allow": ["Bash(git status *)", "Bash(ls *)", "Bash(git push *)", "Read", "mcp__shortcut",
                       "Edit(//state/reviews/**)", "Bash(gh pr *)"],
             "deny": ["Bash(git push --force *)", "mcp__shortcut__stories-update", "Edit(//ws/**)"],
             "ask": ["Bash(gh pr merge *)", "mcp__ld__update-feature-flag"]}

    def d(self, probe, dont_ask=True, servers=None):
        return probes.decide(self.perms, probe, dont_ask, servers)[0]

    def test_compound_needs_every_part(self):
        self.assertEqual(self.d(bash("git status && ls")), "allow")
        self.assertEqual(self.d(bash("cd /x && git status")), "deny")
        self.assertEqual(self.d(bash("cd /x && git status"), dont_ask=False), "prompt")

    def test_deny_beats_allow_in_any_part(self):
        self.assertEqual(self.d(bash("git push --force origin x")), "deny")
        self.assertEqual(self.d(bash("ls; git push --force origin x"), dont_ask=False), "deny")
        self.assertEqual(self.d(bash("git push origin x")), "allow")

    def test_ask_beats_allow(self):
        self.assertEqual(self.d(bash("gh pr merge 1")), "ask")
        self.assertEqual(self.d(bash("gh pr view 1")), "allow")
        self.assertEqual(self.d(tool("mcp__ld__update-feature-flag")), "ask")

    def test_mcp_server_rule(self):
        self.assertEqual(self.d(tool("mcp__shortcut__stories-get-by-id")), "allow")
        self.assertEqual(self.d(tool("mcp__shortcut__stories-update")), "deny")
        self.assertEqual(self.d(tool("mcp__other__x")), "deny")
        self.assertEqual(self.d(tool("mcp__other__x"), dont_ask=False), "prompt")
        self.assertEqual(self.d(tool("mcp__other__x"), servers=["shortcut"]), "unavailable")
        self.assertTrue(probes.tool_rule_matches("mcp__s__*", "mcp__s__t", None))
        self.assertFalse(probes.tool_rule_matches("mcp__s", "mcp__sx__t", None))

    def test_edit_path_globs_cover_write(self):
        self.assertEqual(self.d(tool("Write", "/state/reviews/x.md")), "allow")
        self.assertEqual(self.d(tool("Edit", "/state/reviews/a/b.md")), "allow")
        self.assertEqual(self.d(tool("Write", "/state/other.md")), "deny")
        self.assertEqual(self.d(tool("Write", "/state/other.md"), dont_ask=False), "prompt")
        self.assertEqual(self.d(tool("Write", "/ws/docs/x.md"), dont_ask=False), "deny")
        self.assertEqual(self.d(tool("Grep", "/anywhere")), "allow")

    def test_path_rule_forms(self):
        pm = probes.path_matches
        self.assertTrue(pm("//a/*.md", "/a/x.md", "/s", "/c"))
        self.assertFalse(pm("//a/*.md", "/a/b/x.md", "/s", "/c"))
        self.assertTrue(pm("/x/**", "/s/x/y/z", "/s", "/c"))
        self.assertTrue(pm("src/**", "/c/src/a.py", "/s", "/c"))
        self.assertTrue(pm("~/n/**", os.path.expanduser("~/n/a"), "/s", "/c"))

    def test_bare_tool_and_judge(self):
        self.assertEqual(self.d(tool("Read", "/any")), "allow")
        self.assertEqual(self.d(tool("AskUserQuestion")), "deny")
        self.assertEqual(probes.judge("allow", "prompt"), "warn")
        self.assertEqual(probes.judge("deny", "unavailable"), "pass")
        self.assertEqual(probes.judge("deny", "prompt"), "fail")
        self.assertEqual(probes.judge("ask", "allow"), "fail")


class NormalizeTest(unittest.TestCase):
    ctx = {"workspace": "/ws", "state_dir": "/st", "plugin_root": "/p", "wt": "/st/wt"}

    def test_kinds(self):
        n = probes.normalize
        self.assertEqual(n("mcp__shortcut__stories-update", self.ctx)["kind"], "tool")
        w = n("Write({state_dir}/reviews/x.md)", self.ctx)
        self.assertEqual((w["kind"], w["tool"], w["arg"]), ("tool", "Write", "/st/reviews/x.md"))
        b = n({"cmd": "semgrep --config auto {wt}/x.py", "live": "semgrep --version"}, self.ctx)
        self.assertEqual((b["kind"], b["cmd"], b["live"]), ("bash", "semgrep --config auto /st/wt/x.py", "semgrep --version"))
        self.assertIs(n({"cmd": "gt create", "live": False}, self.ctx)["live"], False)
        self.assertEqual(n("Bash(ls -la)", self.ctx)["cmd"], "ls -la")


class RealTemplatesTest(unittest.TestCase):
    def test_static_run_over_real_templates(self):
        report = probes.run(None, live=False)
        roles = probes.load()
        self.assertEqual({r["role"] for r in report}, set(roles))
        ran = [r for r in report if "skipped" not in r]
        self.assertTrue(any(r["role"] == "reviewer" for r in ran))
        for r in ran:
            self.assertEqual(len(r["results"]), sum(len(roles[r["role"]].get(k, [])) for k in ("allow", "deny", "ask")))
            for x in r["results"]:
                self.assertIn(x["verdict"], ("allow", "deny", "ask", "prompt", "unavailable"))
                self.assertIn(x["status"], ("pass", "warn", "fail"))


if __name__ == "__main__":
    unittest.main()
