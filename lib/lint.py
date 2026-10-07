#!/usr/bin/env python3
# ---
# name: lint
# description: Tier-1 instruction lint over the plugin and its registry — frontmatter, script headers, referenced paths, settings/MCP templates, stale references, near-duplicate rules (warning), registry check. Errors exit 1; warnings never fail.
# usage: lint.py [--json] [--only <check>]... [--plugin <dir>] [--workspace <dir>]
# ---
from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import os
import re
import sys

LIB = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(LIB)
sys.path.insert(0, LIB)

TEXT_DIRS = ("agents", "skills", "commands", "templates")
TEXT_EXT = (".md", ".json")

# Deliberate mentions of retired names: launch.json disables voltus-besstie for every
# launch, migrate_team_json.py converts the old team.json, tests exercise both.
STALE_ALLOW = ("templates/settings/launch.json", "templates/settings/configurator.json",  # deny rules naming it
               "lib/migrate_team_json.py", "lib/test_*.py")
STALE_PATTERNS = (
    ("voltus-besstie", "the retired plugin"),
    ("team.json", "the retired registry (now .claude/prometheus/)"),
    ("ship-review", "a voltus-besstie skill (now prometheus:review)"),
    ("review-lead", "a voltus-besstie agent (now the reviewer)"),
    ("~/.claude/prometheus", "the old state dir (now ~/.local/state/prometheus)"),
    ("docs/vault/", "the voltus-besstie vault (now the knowledge base)"),
)

# Role -> agent, mirroring launch.sh's case; the seat runs the orchestrator agent.
ROLE_AGENTS = {"seat": "orchestrator", "pm": "project-manager"}

# Registry files that legitimately may be absent (machine-local, gitignored).
OPTIONAL_REGISTRY = (".claude/prometheus/local.json",)

PLUGIN_DIRS = ("skills", "lib", "templates", "agents", "commands", "hooks")
PATH_RE = re.compile(r"(?:%s)/[A-Za-z0-9_.*/<>{}-]*" % "|".join(PLUGIN_DIRS))
REF_RE = re.compile(r"references/[A-Za-z0-9_.*<>{}-]+")
REGISTRY_RE = re.compile(r"\.claude/prometheus/[A-Za-z0-9_.*/<>{}-]*")
SKILL_REF_RE = re.compile(r"(?<![\w./-])prometheus:([a-z0-9][a-z0-9-]*)")
BARE_SCRIPT_RE = re.compile(r"(?<![\w./*{}$-])([A-Za-z0-9_-]+\.sh)\b")
DELIM = set(" \t\n`'\"()[],;|=")
ACCEPTED_PREFIXES = ("", "$CLAUDE_PLUGIN_ROOT/", "${CLAUDE_PLUGIN_ROOT}/", "*/", "./")
CHECKS = ("frontmatter", "headers", "paths", "settings", "stale", "duplicates", "registry")


class Ctx:
    def __init__(self, plugin: str, workspace: str | None):
        self.plugin = os.path.abspath(plugin)
        self.workspace = os.path.abspath(workspace) if workspace else None

    def rel(self, path: str) -> str:
        return os.path.relpath(path, self.plugin)


def finding(check: str, severity: str, file: str, line: int, message: str) -> dict:
    return {"check": check, "severity": severity, "file": file, "line": line, "message": message}


def default_workspace(plugin: str) -> str | None:
    env_ws = os.environ.get("WORKSPACE")
    if env_ws and os.path.isdir(os.path.join(env_ws, ".claude", "prometheus")):
        return env_ws
    d = os.path.abspath(plugin)
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, ".claude", "prometheus")):
            return d
        d = os.path.dirname(d)
    return None


def read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


def text_files(ctx: Ctx, exts: tuple | None = TEXT_EXT) -> list[str]:
    out = []
    for d in TEXT_DIRS:
        for root, dirs, files in os.walk(os.path.join(ctx.plugin, d)):
            dirs.sort()
            for f in sorted(files):
                if exts is None or f.endswith(exts):
                    out.append(os.path.join(root, f))
    return out


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


# ------------------------------------------------------------ frontmatter

def parse_frontmatter(text: str) -> dict | None:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    out = {}
    for ln in lines[1:]:
        if ln.strip() == "---":
            return out
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", ln)
        if m:
            out[m.group(1)] = m.group(2).strip().strip("\"'")
    return None


def check_frontmatter(ctx: Ctx) -> list[dict]:
    out = []
    targets = []
    for p in sorted(glob.glob(os.path.join(ctx.plugin, "agents", "*.md"))):
        targets.append((p, "agent", os.path.splitext(os.path.basename(p))[0]))
    for p in sorted(glob.glob(os.path.join(ctx.plugin, "skills", "*", "SKILL.md"))):
        targets.append((p, "skill", os.path.basename(os.path.dirname(p))))
    for p in sorted(glob.glob(os.path.join(ctx.plugin, "commands", "*.md"))):
        targets.append((p, "command", None))
    for d in sorted(glob.glob(os.path.join(ctx.plugin, "skills", "*"))):
        if os.path.isdir(d) and not os.path.isfile(os.path.join(d, "SKILL.md")):
            out.append(finding("frontmatter", "error", ctx.rel(d), 0, "skill dir has no SKILL.md"))
    for path, kind, expect in targets:
        fm = parse_frontmatter(read(path))
        rel = ctx.rel(path)
        if fm is None:
            out.append(finding("frontmatter", "error", rel, 1, "no frontmatter block (--- ... ---)"))
            continue
        if not fm.get("description"):
            out.append(finding("frontmatter", "error", rel, 1, "frontmatter has no description"))
        if kind == "command":
            continue
        name = fm.get("name")
        if not name:
            out.append(finding("frontmatter", "error", rel, 1, "frontmatter has no name"))
        elif name != expect:
            what = "dir" if kind == "skill" else "file stem"
            out.append(finding("frontmatter", "error", rel, 1,
                               "%s name %r does not match its %s %r" % (kind, name, what, expect)))
    return out


# ---------------------------------------------------------------- headers

def parse_header(text: str) -> dict | None:
    lines = text.split("\n")[:40]
    i = 1 if lines and lines[0].startswith("#!") else 0
    if i >= len(lines) or lines[i].strip() != "# ---":
        return None
    out = {}
    for ln in lines[i + 1:]:
        if ln.strip() == "# ---":
            return out
        m = re.match(r"^#\s*([a-z]+):\s*(.*)$", ln)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return None


def header_targets(ctx: Ctx) -> list[tuple[str, bool]]:
    """(path, must_be_executable)."""
    out = []
    for p in sorted(glob.glob(os.path.join(ctx.plugin, "lib", "*.py"))):
        b = os.path.basename(p)
        if b.startswith("test_") or b == "__init__.py":
            continue
        out.append((p, False))
    launch = os.path.join(ctx.plugin, "lib", "launch.sh")
    if os.path.isfile(launch):
        out.append((launch, True))
    for p in sorted(glob.glob(os.path.join(ctx.plugin, "skills", "*", "scripts", "*"))):
        if os.path.isfile(p):
            out.append((p, True))
    return out


def check_headers(ctx: Ctx) -> list[dict]:
    out = []
    for path, exe in header_targets(ctx):
        rel = ctx.rel(path)
        hdr = parse_header(read(path))
        if hdr is None:
            out.append(finding("headers", "error", rel, 1, "no '# ---' header block"))
        else:
            for k in ("name", "description", "usage"):
                if not hdr.get(k):
                    out.append(finding("headers", "error", rel, 1, "header has no %s" % k))
            stem = os.path.splitext(os.path.basename(path))[0]
            if hdr.get("name") and hdr["name"] != stem:
                out.append(finding("headers", "warning", rel, 1,
                                   "header name %r differs from file stem %r" % (hdr["name"], stem)))
        if exe and not os.access(path, os.X_OK):
            out.append(finding("headers", "error", rel, 0, "script is not executable"))
    return out


# ------------------------------------------------------------------ paths

def token_prefix(text: str, start: int) -> str:
    i = start
    while i > 0 and text[i - 1] not in DELIM:
        i -= 1
    return text[i:start]


def clean(path: str) -> str:
    return path.rstrip(".,:;")


def exists_pattern(base: str, path: str) -> bool:
    """A path with <placeholder>/{placeholder} is checked up to that segment; * globs."""
    parts = path.rstrip("/").split("/")
    keep = []
    for part in parts:
        if "<" in part or "{" in part or ">" in part or "}" in part:
            break
        keep.append(part)
    if not keep:
        return True
    probe = os.path.join(base, *keep)
    if "*" in probe:
        return bool(glob.glob(probe))
    return os.path.exists(probe)


def known_scripts(ctx: Ctx) -> set[str]:
    names = set()
    pats = [os.path.join(ctx.plugin, "skills", "*", "scripts", "*"),
            os.path.join(ctx.plugin, "lib", "*"),
            os.path.join(ctx.plugin, "hooks", "*")]
    if ctx.workspace:
        pats.append(os.path.join(ctx.workspace, ".claude", "prometheus", "projects", "*", "*"))
    for pat in pats:
        names.update(os.path.basename(p) for p in glob.glob(pat))
    return names


def known_components(ctx: Ctx) -> set[str]:
    names = set()
    for pat in ("skills/*/SKILL.md",):
        names.update(os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(ctx.plugin, pat)))
    for d in ("agents", "commands"):
        names.update(os.path.splitext(os.path.basename(p))[0]
                     for p in glob.glob(os.path.join(ctx.plugin, d, "*.md")))
    return names


def skill_dir_of(ctx: Ctx, path: str) -> str | None:
    parts = ctx.rel(path).split(os.sep)
    if len(parts) >= 2 and parts[0] == "skills":
        return os.path.join(ctx.plugin, "skills", parts[1])
    return None


def check_paths(ctx: Ctx) -> list[dict]:
    out = []
    scripts = known_scripts(ctx)
    components = known_components(ctx)
    all_refs = {os.path.basename(p) for p in glob.glob(os.path.join(ctx.plugin, "skills", "*", "references", "*"))}
    for path in text_files(ctx):
        text = read(path)
        rel = ctx.rel(path)
        own_skill = skill_dir_of(ctx, path)

        def err(pos, msg):
            out.append(finding("paths", "error", rel, line_of(text, pos), msg))

        for m in PATH_RE.finditer(text):
            prefix = token_prefix(text, m.start())
            if not (prefix in ACCEPTED_PREFIXES or prefix.endswith("plugins/prometheus/")):
                continue
            p = clean(m.group(0))
            if not exists_pattern(ctx.plugin, p):
                err(m.start(), "plugin path %s does not exist" % p)

        for m in REF_RE.finditer(text):
            if token_prefix(text, m.start()) not in ("", "./"):
                continue
            p = clean(m.group(0))
            name = p.split("/", 1)[1]
            if "<" in name or "{" in name or "*" in name:
                continue
            if own_skill and os.path.exists(os.path.join(own_skill, p)):
                continue
            if own_skill is None and name in all_refs:
                continue
            if own_skill and name in all_refs and _names_other_skill(text, m.start(), ctx, name):
                continue
            where = os.path.relpath(own_skill, ctx.plugin) if own_skill else "any skill"
            err(m.start(), "%s not found under %s" % (p, where))

        for m in SKILL_REF_RE.finditer(text):
            if m.group(1) not in components:
                err(m.start(), "prometheus:%s is not a skill, agent or command" % m.group(1))

        for m in BARE_SCRIPT_RE.finditer(text):
            if m.group(1) not in scripts:
                err(m.start(), "script %s exists nowhere in the plugin or the registry" % m.group(1))

        if ctx.workspace:
            for m in REGISTRY_RE.finditer(text):
                p = clean(m.group(0))
                if p in OPTIONAL_REGISTRY or p.rstrip("/") == ".claude/prometheus":
                    continue
                if not exists_pattern(ctx.workspace, p):
                    err(m.start(), "registry path %s does not exist in the workspace" % p)
    return out


def _names_other_skill(text: str, pos: int, ctx: Ctx, name: str) -> bool:
    """A reference into another skill counts when that skill is named on the same line."""
    lo = text.rfind("\n", 0, pos) + 1
    hi = text.find("\n", pos)
    line = text[lo:hi if hi >= 0 else len(text)]
    for d in glob.glob(os.path.join(ctx.plugin, "skills", "*", "references", name)):
        skill = os.path.basename(os.path.dirname(os.path.dirname(d)))
        if re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(skill), line):
            return True
    return False


# --------------------------------------------------------------- settings

RULE_RE = re.compile(r"^[A-Za-z_][\w-]*(\(.+\))?$")


def check_rule(rule, rel: str, line: int) -> list[dict]:
    if not isinstance(rule, str) or not RULE_RE.match(rule):
        return [finding("settings", "error", rel, line, "permission rule %r is not Tool or Tool(...)" % (rule,))]
    if rule.startswith("Write("):
        return [finding("settings", "error", rel, line,
                        "%s: Write(path) rules never match; write path rules are Edit(...)" % rule)]
    m = re.match(r"^(Edit|Read)\((/[^/{].*)\)$", rule)
    if m:
        return [finding("settings", "error", rel, line,
                        "%s: single-slash path is project-relative; an absolute path needs //" % rule)]
    return []


def json_line(text: str, needle: str) -> int:
    pos = text.find(json.dumps(needle))
    return line_of(text, pos) if pos >= 0 else 0


def check_settings(ctx: Ctx) -> list[dict]:
    out = []
    agents = {os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(ctx.plugin, "agents", "*.md"))}

    def role_ok(role: str) -> bool:
        return ROLE_AGENTS.get(role, role) in agents

    for path in sorted(glob.glob(os.path.join(ctx.plugin, "templates", "settings", "*.json"))):
        rel = ctx.rel(path)
        text = read(path)
        try:
            data = json.loads(text)
        except ValueError as exc:
            out.append(finding("settings", "error", rel, getattr(exc, "lineno", 0), "invalid JSON: %s" % exc))
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem != "launch" and not role_ok(stem):
            out.append(finding("settings", "error", rel, 0, "settings for role %r, which maps to no agent" % stem))
        perms = data.get("permissions") or {}
        for key in ("allow", "deny", "ask"):
            rules = perms.get(key) or []
            if not isinstance(rules, list):
                out.append(finding("settings", "error", rel, 0, "permissions.%s is not a list" % key))
                continue
            for rule in rules:
                out += check_rule(rule, rel, json_line(text, rule) if isinstance(rule, str) else 0)

    roles_path = os.path.join(ctx.plugin, "templates", "mcp", "roles.json")
    if os.path.isfile(roles_path):
        rel = ctx.rel(roles_path)
        text = read(roles_path)
        try:
            data = json.loads(text)
        except ValueError as exc:
            return out + [finding("settings", "error", rel, getattr(exc, "lineno", 0), "invalid JSON: %s" % exc)]
        roles = set((data.get("roles") or {}).keys())
        for section in ("writers", "ask_writers"):
            for server, who in (data.get(section) or {}).items():
                roles.update(who or [])
        for role in sorted(roles):
            if not role_ok(role):
                out.append(finding("settings", "error", rel, json_line(text, role),
                                   "role %r maps to no agent (nor the seat)" % role))
    return out


# ------------------------------------------------------------------ stale

def allowlisted(rel: str) -> bool:
    return any(fnmatch.fnmatch(rel, pat) for pat in STALE_ALLOW)


def check_stale(ctx: Ctx) -> list[dict]:
    out = []
    for path in text_files(ctx, exts=None):
        rel = ctx.rel(path)
        if allowlisted(rel):
            continue
        text = read(path)
        for needle, why in STALE_PATTERNS:
            start = 0
            while True:
                pos = text.find(needle, start)
                if pos < 0:
                    break
                out.append(finding("stale", "error", rel, line_of(text, pos), "%r — %s" % (needle, why)))
                start = pos + len(needle)
    return out


# ------------------------------------------------------------- duplicates

DUP_MIN_WORDS = 12
DUP_SHINGLE = 5
DUP_THRESHOLD = 0.8


def strip_markdown(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end >= 0:
            text = "\n" * text.count("\n", 0, end + 4) + text[end + 4:]
    return re.sub(r"```.*?```", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)


def sentences(text: str):
    """Yield (line, words) for each prose sentence."""
    body = strip_markdown(text)
    for m in re.finditer(r"[^\n]+(?:\n(?![ \t]*(?:[-*#>|]|\d+\.|\n))[^\n]+)*", body):
        block = m.group(0)
        base = m.start()
        for s in re.finditer(r"[^.!?]+(?:[.!?](?=\S)[^.!?]*)*[.!?]?", block):
            words = re.sub(r"[^\w\s]", " ", s.group(0).lower()).split()
            if len(words) >= DUP_MIN_WORDS:
                yield line_of(body, base + s.start()), words


def shingles(words: list[str]) -> frozenset:
    return frozenset(tuple(words[i:i + DUP_SHINGLE]) for i in range(len(words) - DUP_SHINGLE + 1))


def check_duplicates(ctx: Ctx) -> list[dict]:
    items = []
    for path in text_files(ctx, exts=(".md",)):
        rel = ctx.rel(path)
        if rel.split(os.sep)[0] not in ("agents", "skills"):
            continue
        for line, words in sentences(read(path)):
            items.append((rel, line, shingles(words)))
    index: dict = {}
    for i, (_, _, sh) in enumerate(items):
        for s in sh:
            index.setdefault(s, []).append(i)
    seen = set()
    out = []
    for i, (fa, la, sa) in enumerate(items):
        cands = set()
        for s in sa:
            cands.update(j for j in index[s] if j > i)
        for j in sorted(cands):
            fb, lb, sb = items[j]
            if fb == fa or (i, j) in seen:
                continue
            jac = len(sa & sb) / len(sa | sb)
            if jac >= DUP_THRESHOLD:
                seen.add((i, j))
                out.append(finding("duplicates", "warning", fa, la,
                                   "near-duplicate (%.2f) of %s:%d — one home per rule" % (jac, fb, lb)))
    return out


# --------------------------------------------------------------- registry

def check_registry(ctx: Ctx) -> list[dict]:
    if not ctx.workspace:
        return [finding("registry", "warning", ".claude/prometheus", 0, "no workspace found; registry not checked")]
    import registry
    return [finding("registry", "error", ".claude/prometheus/" + e.split(" ", 1)[0].rstrip(":"), 0, e)
            for e in registry.check(ctx.workspace)]


# -------------------------------------------------------------------- CLI

RUNNERS = {
    "frontmatter": check_frontmatter,
    "headers": check_headers,
    "paths": check_paths,
    "settings": check_settings,
    "stale": check_stale,
    "duplicates": check_duplicates,
    "registry": check_registry,
}


def run(ctx: Ctx, only: list[str] | None = None) -> list[dict]:
    out = []
    for name in CHECKS:
        if not only or name in only:
            out += RUNNERS[name](ctx)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="lint.py")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only", action="append", choices=CHECKS)
    ap.add_argument("--plugin", default=PLUGIN_ROOT)
    ap.add_argument("--workspace")
    a = ap.parse_args(argv)
    ctx = Ctx(a.plugin, a.workspace or default_workspace(a.plugin))
    found = run(ctx, a.only)
    errors = sum(1 for f in found if f["severity"] == "error")
    if a.json:
        print(json.dumps(found, indent=2))
    else:
        for f in found:
            print("%-7s %-11s %s:%d  %s" % (f["severity"], f["check"], f["file"], f["line"], f["message"]))
        print("%d error(s), %d warning(s)" % (errors, len(found) - errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
