#!/usr/bin/env python3
# ---
# name: probes
# description: Tier-2 allow-list probes — every role's merged settings (lib/launch.sh into a temp state dir) checked against templates/probes.json. Static (default): a local matcher that mirrors Claude Code's permission-rule semantics; free and deterministic. --live: one headless `claude -p` per role with its real launch args under dontAsk, running each Bash allow probe (its `live` form) and failing on any permission denial; costs tokens.
# usage: probes.py [--role R]... [--live] [--json] [--max-turns N]   (exit 1 on any failure)
# ---
# Static matcher — what it models:
#   precedence deny > ask > allow; unmatched = denied under dontAsk (launch arg or defaultMode), else "prompt".
#   Bash: `Bash` / `Bash(*)` = all; `Bash(x)` exact; `*` anywhere = any run of characters; a trailing ` *` also
#   matches the bare command; legacy `Bash(x:*)` = `Bash(x *)`. Compound commands split on unquoted
#   && || ; | & and newlines: any part denied → deny, any part ask → ask, every part allowed → allow.
#   Tools: bare name = every call; `mcp__s` / `mcp__s__*` = every tool of server s; an MCP tool whose server
#   is not in the role's --mcp-config is "unavailable" (counts as refused) — except a built-in server
#   (BUILTIN_SERVERS), present in every session. Edit rules cover Write/MultiEdit/
#   NotebookEdit, Read rules cover Grep/Glob; path rules are gitignore-style (`//abs`, `~/`, `/` = settings
#   dir, else cwd; `**` crosses `/`, `*` does not).
# Limits (live mode is the ground truth):
#   - only the role's merged --settings file; user/project/local settings, managed policy and hooks are ignored.
#   - Claude Code's built-in read-only auto-approvals (ls, cat, pwd, cd inside the working dirs …) and its
#     working-directory read allowance are not modeled — a probe they would approve may read as "prompt".
#   - command substitution ($(…), backticks), subshells and process substitution read as unmatched;
#     redirections, env-var prefixes and wrapper commands (timeout, xargs …) are matched as plain text.
#   - no symlink / realpath resolution of file paths.
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

LIB = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(LIB)
sys.path.insert(0, LIB)
import env  # noqa: E402

PROBES = os.path.join(PLUGIN, "templates", "probes.json")
SCRIPT_DIRS = ("dispatch", "knowledge", "data")
TOOLS = ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep", "Agent", "Skill", "Workflow",
         "AskUserQuestion", "WebFetch", "WebSearch", "Bash")
BUILTIN_SERVERS = ("claude-in-chrome",)  # Claude Code ships it; --strict-mcp-config does not drop it
TOOL_RE = re.compile(r"^(mcp__[\w.-]+|%s)(?:\((.*)\))?$" % "|".join(TOOLS), re.S)
EDIT_FAMILY = {"Write": "Edit", "MultiEdit": "Edit", "NotebookEdit": "Edit", "Glob": "Read", "Grep": "Read"}
FILE_TOOLS = {"Read", "Edit"}


# ---------------------------------------------------------------------- probes

def load(path: str = PROBES) -> dict:
    with open(path) as fh:
        return json.load(fh)["roles"]


def expand(text: str, ctx: dict) -> str:
    for k, v in ctx.items():
        text = text.replace("{%s}" % k, v)
    return text


def normalize(raw, ctx: dict) -> dict:
    """One probe → {kind: bash|tool, cmd, live, tool, arg}."""
    item = raw if isinstance(raw, dict) else {"cmd": raw}
    cmd = expand(item["cmd"], ctx)
    live = item.get("live", None)
    m = TOOL_RE.match(cmd)
    if m and m.group(1) != "Bash":
        return {"kind": "tool", "cmd": cmd, "tool": m.group(1), "arg": m.group(2), "live": False}
    if m and m.group(1) == "Bash" and m.group(2) is not None:
        cmd = m.group(2)
    return {"kind": "bash", "cmd": cmd, "tool": "Bash", "arg": cmd,
            "live": False if live is False else expand(live, ctx) if isinstance(live, str) else None}


# ---------------------------------------------------------------------- matcher

def parse_rule(rule: str) -> tuple[str, str | None]:
    m = re.match(r"^([^()]+?)(?:\((.*)\))?$", rule.strip(), re.S)
    if not m:
        return rule.strip(), None
    return m.group(1), m.group(2)


def split_compound(cmd: str) -> list[str] | None:
    """Unquoted && || ; | & and newlines split; None when the command holds a substitution or bad quoting."""
    parts, cur, i, quote = [], [], 0, None
    while i < len(cmd):
        c = cmd[i]
        if quote:
            if c == "\\" and quote == '"' and i + 1 < len(cmd):
                cur += [c, cmd[i + 1]]
                i += 2
                continue
            if quote == '"' and (c == "`" or cmd.startswith("$(", i)):
                return None
            if c == quote:
                quote = None
            cur.append(c)
            i += 1
            continue
        if c == "\\" and i + 1 < len(cmd):
            cur += [c, cmd[i + 1]]
            i += 2
            continue
        if c in "'\"":
            quote = c
            cur.append(c)
            i += 1
            continue
        if c == "`" or cmd.startswith("$(", i) or cmd.startswith("<(", i) or cmd.startswith(">(", i):
            return None
        two = cmd[i:i + 2]
        if two in ("&&", "||"):
            parts.append("".join(cur))
            cur, i = [], i + 2
            continue
        if c in ";|\n":
            parts.append("".join(cur))
            cur, i = [], i + 1
            continue
        if c == "&":
            prev = cmd[i - 1] if i else ""
            nxt = cmd[i + 1] if i + 1 < len(cmd) else ""
            if prev in "<>" or nxt == ">":  # 2>&1, &>file: a redirection, not a separator
                cur.append(c)
                i += 1
                continue
            parts.append("".join(cur))
            cur, i = [], i + 1
            continue
        if c == "(" and not "".join(cur).strip():
            return None  # subshell
        cur.append(c)
        i += 1
    if quote:
        return None
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def bash_pattern_matches(pattern: str | None, cmd: str) -> bool:
    if pattern is None or pattern.strip() in ("", "*"):
        return True
    pat = pattern.strip()
    if pat.endswith(":*"):
        pat = pat[:-2] + " *"
    tail = pat.endswith(" *")
    if tail:
        pat = pat[:-2]
    rx = ".*".join(re.escape(p) for p in pat.split("*"))
    if tail:
        rx += r"(?:\s.*)?"
    return re.fullmatch(rx, cmd.strip(), re.S) is not None


def glob_to_regex(glob: str) -> str:
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append(r"(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(r".*")
            i += 2
        elif glob[i] == "*":
            out.append(r"[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append(r"[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return "".join(out)


def resolve_rule_path(spec: str, settings_dir: str, cwd: str) -> str:
    if spec.startswith("//"):
        return spec[1:]
    if spec.startswith("~/"):
        return os.path.expanduser("~") + spec[1:]
    if spec.startswith("/"):
        return settings_dir.rstrip("/") + spec
    return os.path.join(cwd, spec[2:] if spec.startswith("./") else spec)


def path_matches(spec: str, path: str, settings_dir: str, cwd: str) -> bool:
    full = resolve_rule_path(spec, settings_dir, cwd)
    if full.endswith("/"):
        full += "**"
    p = os.path.normpath(path)
    return re.fullmatch(glob_to_regex(full), p) is not None or re.fullmatch(glob_to_regex(full), p + "/") is not None


def tool_rule_matches(rule: str, tool: str, arg: str | None, settings_dir: str = "/", cwd: str = "/") -> bool:
    name, content = parse_rule(rule)
    if tool.startswith("mcp__"):
        if content is not None:
            return False
        if name == tool:
            return True
        server = tool.split("__")[1]
        return name in ("mcp__%s" % server, "mcp__%s__*" % server)
    family = EDIT_FAMILY.get(tool, tool)
    if name not in (tool, family):
        return False
    if content is None or content.strip() in ("", "*", "**"):
        return True
    if arg is None:
        return False
    if family in FILE_TOOLS:
        return path_matches(content, arg, settings_dir, cwd)
    return re.fullmatch(glob_to_regex(content), arg) is not None


def _part_verdict(perms: dict, part: str) -> str | None:
    for level in ("deny", "ask", "allow"):
        for rule in perms.get(level, []):
            name, content = parse_rule(rule)
            if name == "Bash" and bash_pattern_matches(content, part):
                return level
    return None


def decide(perms: dict, probe: dict, dont_ask: bool, servers: list[str] | None = None,
           settings_dir: str = "/", cwd: str = "/") -> tuple[str, str]:
    """→ (verdict, reason). verdict ∈ allow | deny | ask | prompt | unavailable."""
    unmatched = ("deny", "no rule matches (dontAsk)") if dont_ask else ("prompt", "no rule matches")
    if probe["kind"] == "bash":
        parts = split_compound(probe["cmd"])
        if parts is None:
            return unmatched[0], "substitution/subshell — not statically matched"
        verdicts = [_part_verdict(perms, p) for p in parts]
        for level in ("deny", "ask"):
            if level in verdicts:
                return level, "part %r" % parts[verdicts.index(level)]
        if all(v == "allow" for v in verdicts):
            return "allow", "every part allowed" if len(parts) > 1 else "allowed"
        miss = parts[verdicts.index(None)]
        return unmatched[0], "%s: %r" % (unmatched[1], miss) if len(parts) > 1 else unmatched[1]
    tool, arg = probe["tool"], probe["arg"]
    server = tool.split("__")[1] if tool.startswith("mcp__") else None
    if server and servers is not None and server not in servers and server not in BUILTIN_SERVERS:
        return "unavailable", "server not in the role's --mcp-config"
    for level in ("deny", "ask", "allow"):
        for rule in perms.get(level, []):
            if tool_rule_matches(rule, tool, arg, settings_dir, cwd):
                return level, rule
    return unmatched


def judge(expect: str, verdict: str) -> str:
    """pass | warn | fail for a probe in list `expect` given the verdict."""
    if expect == "allow":
        return "pass" if verdict == "allow" else "warn" if verdict == "prompt" else "fail"
    if expect == "deny":
        return "pass" if verdict in ("deny", "unavailable") else "fail"
    return "pass" if verdict == "ask" else "fail"


# ---------------------------------------------------------------------- roles

class Skip(Exception):
    pass


def generate(role: str, state_dir: str) -> dict:
    """launch.sh <role> --args into state_dir → {args, settings, settings_path, servers, dont_ask}."""
    e = dict(os.environ, PROMETHEUS_STATE_DIR=state_dir)
    out = subprocess.run([os.path.join(LIB, "launch.sh"), role, "--args"], capture_output=True, text=True,
                         env=e, timeout=60)
    if out.returncode != 0:
        raise Skip((out.stderr.strip() or "launch.sh exited %d" % out.returncode).splitlines()[-1])
    args = json.loads(out.stdout)
    spath = os.path.join(state_dir, "settings", role + ".json")
    with open(spath) as fh:
        settings = json.load(fh)
    try:
        with open(os.path.join(state_dir, "mcp", role + ".json")) as fh:
            servers = list(json.load(fh).get("mcpServers", {}))
    except (OSError, ValueError):
        servers = []
    perms = settings.get("permissions") or {}
    dont_ask = perms.get("defaultMode") == "dontAsk" or any(
        a == "--permission-mode" and b == "dontAsk" for a, b in zip(args, args[1:]))
    return {"args": args, "settings": settings, "settings_path": spath, "servers": servers, "dont_ask": dont_ask}


def context(state_dir: str) -> dict:
    return {"workspace": env.workspace_root(), "state_dir": state_dir, "plugin_root": PLUGIN,
            "wt": os.path.join(state_dir, "probe-wt-missing")}


def static_role(role: str, spec: dict, state_dir: str) -> dict:
    gen = generate(role, state_dir)
    ctx = context(state_dir)
    perms = gen["settings"].get("permissions") or {}
    results = []
    for expect in ("allow", "deny", "ask"):
        for raw in spec.get(expect, []):
            p = normalize(raw, ctx)
            verdict, reason = decide(perms, p, gen["dont_ask"], gen["servers"],
                                     os.path.dirname(gen["settings_path"]), ctx["workspace"])
            results.append({"expect": expect, "probe": p["cmd"], "verdict": verdict, "reason": reason,
                            "status": judge(expect, verdict)})
    return {"role": role, "dont_ask": gen["dont_ask"], "results": results}


# ---------------------------------------------------------------------- live

LIVE_PROMPT = """PERMISSION PROBE — not a work request. Ignore your role instructions for this turn: message no one, read and write nothing else.
Run each command below with the Bash tool exactly as written (byte for byte: no cd, no added flags, no quoting changes), one Bash call per command, in the listed order. A command failing, erroring or being denied is expected: do not retry, do not work around it, continue to the next. After the last one reply with the single word DONE.
"""


def _strip_mode(args: list[str]) -> list[str]:
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a == "--permission-mode":
            skip = True
            continue
        out.append(a)
    return out


def live_role(role: str, spec: dict, state_dir: str, max_turns: int | None = None) -> dict:
    gen = generate(role, state_dir)
    ctx = context(state_dir)
    probes = []
    for expect in ("allow", "deny"):
        for raw in spec.get(expect, []):
            p = normalize(raw, ctx)
            if p["kind"] != "bash" or p["live"] is False or (expect == "deny" and not p["live"]):
                continue
            probes.append({"expect": expect, "probe": p["cmd"], "run": p["live"] or p["cmd"]})
    if not probes:
        return {"role": role, "results": [], "note": "no live Bash probes"}
    prompt = LIVE_PROMPT + "\n".join("%d. %s" % (i + 1, p["run"]) for i, p in enumerate(probes))
    turns = max_turns or len(probes) + 4
    cmd = ["claude", "-p", prompt, *_strip_mode(gen["args"]), "--permission-mode", "dontAsk", "--tools", "Bash",
           "--max-turns", str(turns), "--output-format", "stream-json", "--verbose"]
    scripts = os.pathsep.join(os.path.join(PLUGIN, "skills", s, "scripts") for s in SCRIPT_DIRS)
    e = dict(os.environ, PROMETHEUS_STATE_DIR=state_dir, PROMETHEUS_ROLE=role, WORKSPACE=ctx["workspace"],
             PATH=scripts + os.pathsep + os.environ.get("PATH", ""))
    e.pop("HERDR_ENV", None)
    cwd = os.path.join(state_dir, "cwd")
    os.makedirs(cwd, exist_ok=True)
    out = subprocess.run(cmd, capture_output=True, text=True, env=e, cwd=cwd, timeout=900)
    ran, final = [], None
    for line in out.stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_use" and block.get("name") == "Bash":
                    ran.append((block.get("input") or {}).get("command", "").strip())
        elif ev.get("type") == "result":
            final = ev
    if final is None:
        return {"role": role, "error": "no result event (exit %d): %s" % (out.returncode, out.stderr.strip()[-400:]),
                "results": []}
    denied = [(d.get("tool_input") or {}).get("command", "").strip()
              for d in final.get("permission_denials") or [] if d.get("tool_name") == "Bash"]
    results = []
    for p in probes:
        run = p["run"].strip()
        if run not in ran:
            verdict = "not-run"
        else:
            verdict = "deny" if run in denied else "allow"
        status = "fail" if verdict == "not-run" else judge(p["expect"], verdict)
        results.append({**p, "verdict": verdict, "status": status})
    return {"role": role, "results": results, "cost_usd": final.get("total_cost_usd"),
            "turns": final.get("num_turns"), "subtype": final.get("subtype"),
            "unexpected_denials": [d for d in denied if d not in {p["run"].strip() for p in probes}]}


# ---------------------------------------------------------------------- cli

def run(roles: list[str] | None, live: bool, max_turns: int | None = None, path: str = PROBES) -> list[dict]:
    spec = load(path)
    out = []
    for role in roles or list(spec):
        if role not in spec:
            out.append({"role": role, "skipped": "no probes for role"})
            continue
        state = tempfile.mkdtemp(prefix="prometheus-probes-")
        try:
            out.append(live_role(role, spec[role], state, max_turns) if live else static_role(role, spec[role], state))
        except Skip as exc:
            out.append({"role": role, "skipped": str(exc)})
        finally:
            shutil.rmtree(state, ignore_errors=True)
    return out


def failed(report: list[dict]) -> bool:
    return any(r.get("error") or any(x["status"] == "fail" for x in r.get("results", [])) for r in report)


def render(report: list[dict], live: bool) -> str:
    lines = []
    for r in report:
        if "skipped" in r:
            lines.append("== %s: skipped (%s)" % (r["role"], r["skipped"]))
            continue
        head = "== %s" % r["role"]
        if live:
            head += " (live: %s turns, $%.2f)" % (r.get("turns"), r.get("cost_usd") or 0)
        elif r.get("dont_ask") is not None:
            head += " (%s)" % ("dontAsk" if r["dont_ask"] else "prompts")
        lines.append(head)
        if r.get("error"):
            lines.append("  ERROR %s" % r["error"])
        for x in r.get("results", []):
            tag = {"pass": "ok  ", "warn": "WARN", "fail": "FAIL"}[x["status"]]
            lines.append("  %s %-5s → %-11s %s%s" % (tag, x["expect"], x["verdict"], x.get("run") or x["probe"],
                                                    ("   [%s]" % x["reason"]) if x.get("reason") and x["status"] != "pass" else ""))
        for d in r.get("unexpected_denials") or []:
            lines.append("  note: denied outside the probe list: %s" % d)
    n = [x["status"] for r in report for x in r.get("results", [])]
    lines.append("%d probes: %d ok, %d warn, %d fail" % (len(n), n.count("pass"), n.count("warn"), n.count("fail")))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="probes.py")
    ap.add_argument("--role", action="append")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-turns", type=int)
    ap.add_argument("--probes", default=PROBES)
    a = ap.parse_args(argv)
    report = run(a.role, a.live, a.max_turns, a.probes)
    print(json.dumps(report, indent=1) if a.json else render(report, a.live))
    return 1 if failed(report) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
