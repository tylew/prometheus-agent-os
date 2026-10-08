#!/usr/bin/env python3
# ---
# name: events
# description: External event sources and what the dispatcher does with them — GitHub PR polling (review requested, authored, and every PR a unit holds), PR stacks, Shortcut polling through one claude -p call, matching to units, triage of the unmatched, auto-created review units, seat proposals, KB settle on story completion, and lead-session health. Called once per tick by dispatch.tick; the poll-github / poll-shortcut / pr-stack / match-event / triage-event / health scripts wrap its subcommands.
# usage: events.py {poll-github|poll-shortcut|pr-stack <repo> <n>|match <event-json>|triage <event-json>|health|proposal approve|decline <id>}
# ---
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

LIB = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(LIB)
sys.path.insert(0, LIB)
import dispatch  # noqa: E402

STORY_RE = re.compile(r"\bsc[-_ ]?(\d{4,})\b|shortcut\.com/[^/\s]+/story/(\d+)", re.I)
PR_FIELDS = ("number,title,body,state,isDraft,mergedAt,closedAt,headRefName,baseRefName,"
             "headRefOid,reviewDecision,latestReviews,comments,statusCheckRollup,url,author")
DONE_STATES = ("Completed",)
DROP_STATES = ("Won't Fix",)
HEALTH_COOLDOWN = 600
NEW_PER_TICK = int(os.environ.get("PROMETHEUS_NEW_PER_TICK", 3))
OWNED_INTERVAL = int(os.environ.get("OWNED_INTERVAL", 600))
REVIEW_SOURCES = ("review-requested", "owned-paths")


def run(cmd: list[str], timeout: int = 120, cwd: str | None = None, stdin: str | None = None,
        check: bool = True) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
                             input=stdin if stdin is not None else "")
    except subprocess.TimeoutExpired:
        raise RuntimeError("%s: timed out after %ss" % (" ".join(cmd[:3]), timeout))
    if out.returncode != 0 and (check or not out.stdout.strip()):
        raise RuntimeError("%s: %s" % (" ".join(cmd[:3]), (out.stderr or out.stdout).strip()[:300]))
    return out.stdout


def gh_json(*args: str):
    return json.loads(run([os.environ.get("GH_BIN", "gh"), *args]) or "null")


# ------------------------------------------------------------------- GitHub

def pr_ref(repo: str, number) -> str:
    return "%s#%s" % (repo, number)


def split_ref(ref: str) -> tuple[str, str]:
    repo, num = dispatch.canon_ref("prs", ref).rsplit("#", 1)
    return repo, num


def stories_in(*texts: str) -> list[str]:
    seen = []
    for t in texts:
        for m in STORY_RE.finditer(t or ""):
            sid = "sc-%s" % (m.group(1) or m.group(2))
            if sid not in seen:
                seen.append(sid)
    return seen


def ci_state(rollup: list[dict]) -> str:
    states = [(c.get("conclusion") or c.get("state") or c.get("status") or "").upper() for c in rollup or []]
    if not states:
        return "none"
    if any(s in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED") for s in states):
        return "fail"
    if any(s in ("", "PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED", "WAITING") for s in states):
        return "pending"
    return "pass"


NOISE_LOGIN = re.compile(r"(\[bot\]$|-integration$|^github-actions$|^dependabot|^renovate|^codecov|^graphite-app)", re.I)
NOISE_BODY = ("<!-- PESTO", "app.graphite.com/github/pr/", "This pull request has been linked to [Shortcut")


def is_noise(author: str, body: str, ignore: list[str] | None = None) -> bool:
    """Integration bots and tool-generated comments (Graphite stack list, CI artifacts, tracker link-back)
    never change anyone's next move."""
    if author in (ignore or []) or NOISE_LOGIN.search(author or ""):
        return True
    return any(m in (body or "")[:400] for m in NOISE_BODY)


def own_posts() -> tuple[str, str]:
    """(operator login, rendered signature): prometheus posts as the operator, and its own posts are no news."""
    try:
        import registry
        op = (registry.workspace_config() or {}).get("operator") or {}
    except (ImportError, RuntimeError, ValueError, OSError):
        return "", ""
    sig = (op.get("signature") or "⚡ Prometheus by instruction of {name}").format(
        name=op.get("name", ""), full_name=op.get("full_name", ""), github=op.get("github", ""))
    return op.get("github", ""), sig


def is_own(author: str, body: str, own: tuple[str, str] | None) -> bool:
    """A signed post, or a body-less review (thread replies), from the operator's account is prometheus's own."""
    login, sig = own or ("", "")
    return bool(login) and author == login and (not (body or "").strip() or bool(sig) and sig in body)


def _ignore_authors(repo: str) -> list[str]:
    try:
        import registry
        key = registry.repo_projects().get(repo)
        return registry.field("review.ignore_authors", key=key, default=[]) if key else []
    except (ImportError, RuntimeError, ValueError):
        return []


def fingerprint(pr: dict, ignore: list[str] | None = None, own: tuple[str, str] | None = None) -> dict:
    def news(x):
        who, body = (x.get("author") or {}).get("login", ""), x.get("body", "")
        return not is_noise(who, body, ignore) and not is_own(who, body, own)
    reviews = [r for r in pr.get("latestReviews") or [] if news(r)]
    comments = [c for c in pr.get("comments") or [] if news(c)]
    last = max(reviews, key=lambda r: r.get("submittedAt") or "", default={})
    state = "merged" if pr.get("mergedAt") else (pr.get("state") or "").lower()
    return {"state": state, "draft": bool(pr.get("isDraft")), "head": pr.get("headRefOid"),
            "ci": ci_state(pr.get("statusCheckRollup")), "decision": pr.get("reviewDecision") or "",
            "review": "%s:%s" % (last.get("author", {}).get("login", ""), last.get("state", "")) if last else "",
            "review_at": last.get("submittedAt", ""), "comments": len(comments),
            # not compared by pr_changes — the map and epic routing read them
            "stories": stories_in(pr.get("title"), pr.get("body"), pr.get("headRefName")),
            "author": (pr.get("author") or {}).get("login", "")}


def pr_changes(ref: str, old: dict | None, new: dict) -> list[str]:
    """Only changes that alter someone's next move."""
    if old is None:
        return ["new"]
    out = []
    if new["state"] != old["state"] and new["state"] in ("merged", "closed"):
        out.append(new["state"])
    if new["ci"] != old["ci"] and new["ci"] in ("pass", "fail"):
        out.append("ci %s" % new["ci"])
    if new["review_at"] > old.get("review_at", "") and new["review"]:  # a dismissed review falls back to an older one
        out.append("review %s" % new["review"])
    if new["comments"] > old["comments"]:
        out.append("%d new comment(s)" % (new["comments"] - old["comments"]))
    if new["head"] != old["head"] and old["head"]:
        out.append("new commits")
    if new["draft"] != old["draft"]:
        out.append("ready for review" if not new["draft"] else "back to draft")
    return out


def watched_repos() -> list[str]:
    """Repos the dispatcher may poll: the registry's project repos (step 4), until then PROMETHEUS_REPOS."""
    try:
        import registry
        repos = registry.repos()
        if repos:
            return repos
    except (ImportError, AttributeError, RuntimeError, ValueError, SystemExit):
        pass
    return dispatch._csv(os.environ.get("PROMETHEUS_REPOS"))


def search_prs(query: str, repos: list[str]) -> list[str]:
    args = ["search", "prs", query, "--state", "open", "--json", "number,repository", "--limit", "50"]
    for repo in repos:
        args += ["--repo", repo]
    rows = gh_json(*args)
    return [pr_ref(r["repository"]["nameWithOwner"], r["number"]) for r in rows or []]


def owned_paths_by_repo() -> dict:
    """repo slug → [(owned path, project key)] for editable projects, longest path first."""
    out = {}
    try:
        import registry
        for key, e in (registry.projects() or {}).items():
            slug = registry.dig(e, "repo.slug")
            if e.get("access") == "editable" and slug:
                for path in e.get("owned_paths") or []:
                    out.setdefault(slug, []).append((path.rstrip("/") + "/", key))
    except (ImportError, AttributeError, RuntimeError, ValueError, SystemExit):
        pass
    return {k: sorted(v, key=lambda x: -len(x[0])) for k, v in out.items()}


def poll_owned(st: dict, now: float | None = None) -> list[str]:
    """Teammates' open, non-draft PRs touching an owned path — at most every OWNED_INTERVAL. The first
    poll is a baseline: what is already open goes to the seat as one line, never to automatic units."""
    now = now or time.time()
    o = st.setdefault("owned", {"at": 0, "prs": [], "baseline": False})
    if now - o.get("at", 0) < OWNED_INTERVAL:
        return []
    o["at"] = int(now)
    found = {}
    for slug, paths in owned_paths_by_repo().items():
        rows = gh_json("pr", "list", "-R", slug, "--state", "open", "--search", "draft:false -author:@me",
                       "--json", "number,files", "--limit", "100") or []
        for row in rows:
            files = [f.get("path", "") for f in row.get("files") or []]
            if any(f.startswith(p) for f in files for p, _ in paths):
                found[pr_ref(slug, row["number"])] = True
    lines = []
    if not o.get("baseline"):
        o["baseline"] = True
        o["seen_at_baseline"] = sorted(found)
        if found:
            lines.append("[prometheus] %d open teammate PR(s) already touch your owned paths: %s — none "
                         "auto-reviewed; name any to review" % (len(found), ", ".join(sorted(found))))
    o["prs"] = sorted(r for r in found if r not in o.get("seen_at_baseline", []))
    return lines


def review_verdict(ev: dict) -> dict | None:
    """A review request or an owned-paths PR needs no model: the repo names the project, the PR the unit."""
    if ev["kind"] != "pr" or ev.get("source") not in REVIEW_SOURCES:
        return None
    repo, num = split_ref(ev["pr"])
    project = repo_projects().get(repo)
    if not project:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"^[\w-]+:\s*", "", ev.get("title") or "").lower()).strip("-")
    name = ("review-%s-%s" % (num, "-".join(slug.split("-")[:5]))).strip("-")[:48].strip("-")
    why = "review requested" if ev["source"] == "review-requested" else "touches the operator's owned paths"
    return {"decision": "new", "reason": why,
            "proposal": {"kind": "review", "project": project, "name": name, "prs": ev.get("stack") or [ev["pr"]]}}


def view_pr(ref: str) -> dict:
    repo, num = split_ref(ref)
    return gh_json("pr", "view", num, "-R", repo, "--json", PR_FIELDS)


def poll_github(snap: dict, st: dict) -> list[dict]:
    repos = watched_repos()
    if not repos:
        raise RuntimeError("no watched repos (registry or PROMETHEUS_REPOS); GitHub not polled")
    review = set(search_prs("--review-requested=@me", repos))
    authored = set(search_prs("--author=@me", repos))
    owned = set(st.get("owned", {}).get("prs", []))
    held = {r for u in dispatch.units(snap) for r in dispatch._csv(dispatch._tokens(u).get("prs"))}
    events, fresh, own = [], 0, own_posts()
    for ref in sorted(review | authored | owned | held):
        key = "pr:" + ref
        old = st["cursors"].get(key)
        if old is None and ref not in held:
            if fresh >= NEW_PER_TICK:
                continue  # left unseen: it comes back as new on a later tick
            fresh += 1
        try:
            pr = view_pr(ref)
        except (RuntimeError, ValueError) as exc:
            events.append({"kind": "error", "line": "gh %s: %s" % (ref, exc)})
            continue
        new = fingerprint(pr, _ignore_authors(split_ref(ref)[0]), own)
        st["cursors"][key] = new
        for change in pr_changes(ref, old, new):
            if change == "new" and ref in held:
                continue
            events.append({
                "kind": "pr", "pr": ref, "change": change, "title": pr.get("title", ""),
                "stories": stories_in(pr.get("title"), pr.get("body"), pr.get("headRefName")),
                "source": "review-requested" if ref in review else ("authored" if ref in authored else
                                                                   ("owned-paths" if ref in owned else "unit")),
                "line": "[prometheus] pr %s %s — %s" % (ref, change, pr.get("title", "")),
            })
    return events


def pr_stack(ref: str, _cache: dict | None = None) -> list[str]:
    """Every PR in ref's stack: walk bases down to the default branch, then children by head."""
    repo, num = split_ref(ref)
    cache = _cache if _cache is not None else {}
    if repo not in cache:
        cache[repo] = gh_json("pr", "list", "-R", repo, "--state", "open", "--limit", "200",
                              "--json", "number,headRefName,baseRefName") or []
    open_prs = cache[repo]
    by_head = {p["headRefName"]: p for p in open_prs}
    by_num = {str(p["number"]): p for p in open_prs}
    start = by_num.get(num) or view_pr(ref)
    members = {str(start["number"]): start}
    cur = start
    while cur.get("baseRefName") in by_head:
        cur = by_head[cur["baseRefName"]]
        if str(cur["number"]) in members:
            break
        members[str(cur["number"])] = cur
    frontier = list(members.values())
    while frontier:
        p = frontier.pop()
        for child in open_prs:
            if child.get("baseRefName") == p["headRefName"] and str(child["number"]) not in members:
                members[str(child["number"])] = child
                frontier.append(child)
    return sorted((pr_ref(repo, n) for n in members), key=lambda r: int(split_ref(r)[1]))


# ----------------------------------------------------------------- Shortcut

SHORTCUT_SCHEMA = {
    "type": "object", "required": ["stories"],
    "properties": {"stories": {"type": "array", "items": {
        "type": "object", "required": ["id", "name", "state"],
        "properties": {"id": {"type": "string", "pattern": "^sc-[0-9]+$"}, "name": {"type": "string"},
                       "state": {"type": "string"}, "epic": {"type": "string"},
                       "epic_id": {"type": "string", "pattern": "^[0-9]*$"},
                       "updated_at": {"type": "string"}}}}},
}


SHORTCUT_READ_TOOLS = ["mcp__shortcut__stories-search", "mcp__shortcut__stories-get-by-id"]
SHORTCUT_DONE = ("Completed", "Won't Fix")


def claude_json(prompt: str, schema: dict, *, agent: str | None = None, mcp: dict | None = None,
                allowed: list[str] | None = None, model: str = "haiku", timeout: int = 180,
                budget: float | None = None) -> dict:
    """One-shot claude -p with structured output, outside the workspace so no CLAUDE.md loads."""
    cmd = [os.environ.get("CLAUDE_BIN", "claude"), "-p", "--model", model, "--output-format", "json",
           "--json-schema", json.dumps(schema),
           "--settings", os.path.join(PLUGIN, "templates", "settings", "launch.json"),
           "--max-budget-usd", "%.2f" % (budget or float(os.environ.get("PROMETHEUS_ONESHOT_BUDGET", "0.25")))]
    if agent:
        cmd += ["--plugin-dir", PLUGIN, "--agent", agent]
    if mcp is not None:
        cfg = os.path.join(dispatch.state_dir(), "mcp-oneshot.json")
        with open(cfg, "w") as fh:
            json.dump({"mcpServers": mcp}, fh)
        cmd += ["--strict-mcp-config", "--mcp-config", cfg, "--tools", ""]  # MCP tools only: no Bash to wander into
    else:
        cmd += ["--strict-mcp-config"]
    if allowed:
        cmd += ["--allowed-tools", ",".join(allowed)]
    # prompt on stdin: --mcp-config is variadic and would swallow a positional prompt
    out = json.loads(run(cmd, timeout=timeout, cwd=tempfile.gettempdir(), stdin=prompt, check=False))
    if out.get("permission_denials"):
        denied = sorted({d.get("tool_name", "?") for d in out["permission_denials"]})
        raise RuntimeError("claude -p denied %s; its answer is not trusted" % ", ".join(denied))
    if out.get("is_error") or "structured_output" not in out:
        raise RuntimeError("claude -p %s after %s turns, $%.2f: %s" % (
            out.get("subtype"), out.get("num_turns"), out.get("total_cost_usd") or 0, str(out.get("result"))[:200]))
    return out["structured_output"]


def poll_shortcut(snap: dict, st: dict, now: float | None = None) -> list[dict]:
    now = now or time.time()
    every = int(os.environ.get("SHORTCUT_INTERVAL", 1800))
    if now - st["cursors"].get("shortcut:polled", 0) < every:
        return []
    since = st["cursors"].get("shortcut:since") or time.strftime("%Y-%m-%d", time.gmtime(now - 7 * 86400))
    held = {s for u in dispatch.units(snap) for s in dispatch.token_list(dispatch._tokens(u), "stories")}
    fetch = sorted((s for s in held if st["cursors"].get("story:" + s) not in SHORTCUT_DONE),
                   key=lambda s: int(s.split("-")[1]))
    prompt = ("Read-only Shortcut poll. Make exactly these calls and no others:\n"
              "1. stories-search once with owner \"me\" and updated \"%s..*\" (the result already carries "
              "each story's name, workflow state and epic; do not fetch those one by one).\n"
              "2. stories-get-by-id for each of these ids the search did not return: %s.\n"
              "Return every story from steps 1–2 once: id as sc-<number>, name, workflow state name, epic name, "
              "epic_id (the epic's numeric id; empty when the story has no epic), updated_at." % (since, ", ".join(s.split("-")[1] for s in fetch) or "none"))
    mcp = {"shortcut": {"type": "http", "url": os.environ.get("SHORTCUT_MCP_URL", "https://mcp.shortcut.com/mcp")}}
    result = claude_json(prompt, SHORTCUT_SCHEMA, mcp=mcp, allowed=SHORTCUT_READ_TOOLS,
                         budget=0.10 + 0.04 * len(fetch))  # ~$0.02 per turn measured; one turn per fetched id
    st["cursors"]["shortcut:polled"] = int(now)
    st["cursors"]["shortcut:since"] = time.strftime("%Y-%m-%d", time.gmtime(now))
    events, fresh = [], 0
    for s in result.get("stories", []):
        remember_epic(st, s["id"], s.get("epic_id", ""), s.get("epic", ""), now)
        key = "story:" + s["id"]
        old = st["cursors"].get(key)
        if old is None and s["id"] not in held:
            if fresh >= NEW_PER_TICK:
                st["cursors"]["shortcut:since"] = since  # re-list the rest next poll
                continue
            fresh += 1
        st["cursors"][key] = s["state"]
        if old == s["state"]:
            continue
        change = "new" if old is None else "%s → %s" % (old, s["state"])
        if change == "new" and s["id"] in held:
            continue
        events.append({"kind": "story", "story": s["id"], "state": s["state"], "change": change,
                       "title": s.get("name", ""), "epic": s.get("epic", ""),
                       "line": "[prometheus] story %s %s — %s" % (s["id"], change, s.get("name", ""))})
    return events


# -------------------------------------------------------------------- epics

EPIC_SCHEMA = {
    "type": "object", "required": ["stories"],
    "properties": {"stories": {"type": "array", "items": {
        "type": "object", "required": ["id", "epic_id"],
        "properties": {"id": {"type": "string", "pattern": "^sc-[0-9]+$"},
                       "epic_id": {"type": "string", "pattern": "^[0-9]*$"}, "epic": {"type": "string"}}}}},
}
EPIC_LOOKUP_PER_TICK = int(os.environ.get("PROMETHEUS_EPIC_LOOKUPS", 6))
NO_EPIC_RECHECK = 1800  # a story found without an epic is looked up again after this long (it may be homed)


def remember_epic(st: dict, story: str, epic_id: str, epic_name: str, now: float | None = None) -> None:
    st.setdefault("story_epic", {})[story] = {"id": epic_id or "", "name": epic_name or "", "at": int(now or time.time())}


def lookup_epics(st: dict, stories: list[str], fn=None, now: float | None = None) -> None:
    """One batched read-only Shortcut lookup for stories whose epic is not cached (or was empty a while ago)."""
    now = now or time.time()
    cache = st.setdefault("story_epic", {})
    need = [s for s in dict.fromkeys(stories)
            if s not in cache or (not cache[s]["id"] and now - cache[s].get("at", 0) > NO_EPIC_RECHECK)]
    need = need[:EPIC_LOOKUP_PER_TICK]
    if not need:
        return
    fn = fn or (lambda ids: claude_json(
        "Read-only Shortcut lookup. Call stories-get-by-id once for each of these ids and nothing else — no "
        "files, comments, attachments or searches; the story record already carries its epic: %s. "
        "Return each as id sc-<number>, epic_id (the epic's numeric id; empty when none), epic (its name)."
        % ", ".join(i.split("-")[1] for i in ids), EPIC_SCHEMA,
        mcp={"shortcut": {"type": "http", "url": os.environ.get("SHORTCUT_MCP_URL", "https://mcp.shortcut.com/mcp")}},
        allowed=["mcp__shortcut__stories-get-by-id"], budget=0.06 + 0.03 * len(ids)))
    for row in fn(need).get("stories", []):
        remember_epic(st, row["id"], row.get("epic_id", ""), row.get("epic", ""), now)


def epic_of(st: dict, stories: list[str]) -> tuple[str, str] | None:
    for s in stories:
        e = st.get("story_epic", {}).get(s)
        if e and e["id"]:
            return e["id"], e["name"]
    return None


def epic_unit_name(epic_id: str, epic_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (epic_name or "").lower()).strip("-")
    return ("epic-%s-%s" % (epic_id, "-".join(slug.split("-")[:4]))).strip("-")[:40].strip("-")


def default_project() -> str | None:
    if os.environ.get("PROMETHEUS_DEFAULT_PROJECT"):
        return os.environ["PROMETHEUS_DEFAULT_PROJECT"]
    try:
        import registry
        return ((registry.workspace_config() or {}).get("trackers", {}).get("shortcut") or {}).get("default_project")
    except Exception:  # noqa: BLE001 — no registry: the seat is asked instead
        return None


# ------------------------------------------------------------------- triage

TRIAGE_SCHEMA_PATH = os.path.join(PLUGIN, "templates", "triage-result.json")


def repo_projects() -> dict:
    """repo slug → registry project key: the registry (step 4), until then PROMETHEUS_REPO_PROJECTS."""
    try:
        import registry
        mapping = registry.repo_projects()
        if mapping:
            return mapping
    except (ImportError, AttributeError, RuntimeError, ValueError, SystemExit):
        pass
    pairs = [p.split("=", 1) for p in dispatch._csv(os.environ.get("PROMETHEUS_REPO_PROJECTS")) if "=" in p]
    return {k.strip(): v.strip() for k, v in pairs}


def project_keys() -> list[str]:
    try:
        import registry
        editable = {k for k, e in (registry.projects() or {}).items() if e.get("access") == "editable"}
    except (ImportError, RuntimeError, ValueError):
        editable = set()
    keys = sorted(editable | set(repo_projects().values()) | set(dispatch._csv(os.environ.get("PROMETHEUS_PROJECTS"))))
    return keys or ["unknown"]


def triage(event: dict, snap: dict) -> dict:
    schema = json.load(open(TRIAGE_SCHEMA_PATH))
    for k in ("$schema", "title", "description"):
        schema.pop(k, None)
    schema["properties"]["proposal"]["properties"]["project"] = {"enum": project_keys()}
    live = [{"unit": dispatch._tokens(u).get("unit"), "kind": dispatch._tokens(u).get("kind"),
             "project": dispatch._tokens(u).get("project"), "stories": dispatch._tokens(u).get("stories"),
             "prs": dispatch._tokens(u).get("prs")} for u in dispatch.units(snap)]
    payload = {"event": {k: v for k, v in event.items() if k != "line"}, "live_units": live,
               "project_keys": project_keys(),
               "naming": {"story": "sc-<id>-<slug>", "story-set": "<theme-slug>",
                          "goal-set": "<goal-slug>", "review": "review-<root-pr-number>-<slug>"}}
    return claude_json("Classify this event.\n" + json.dumps(payload), schema, agent="prometheus:triage")


def check_verdict(ev: dict, verdict: dict, snap: dict) -> str | None:
    """None when the verdict is actionable; else why not."""
    d = verdict.get("decision")
    if d == "ignore":
        return None
    if d == "attach":
        names = {dispatch._tokens(u).get("unit") for u in dispatch.units(snap)}
        return None if verdict.get("attach_to") in names else "attach_to %r is not a live unit" % verdict.get("attach_to")
    if d == "new":
        prop = verdict.get("proposal") or {}
        missing = [k for k in ("kind", "name") if not prop.get(k)]
        if missing:
            return "proposal missing %s" % ", ".join(missing)
        if ev["kind"] == "pr":
            prop["project"] = repo_projects().get(split_ref(ev["pr"])[0]) or prop.get("project")
        if not prop.get("project") or prop["project"] == "unknown":
            return "no project for %s" % _subject(ev)
        return None
    return "unknown decision %r" % d


# ---------------------------------------------------------------- handling

def _guard_tokens_lost(snap: dict) -> list[str]:
    """Workspaces that look like units (a pm / planner tab) but carry no unit token."""
    tagged = {u["workspace_id"] for u in dispatch.units(snap)}
    return sorted({t["workspace_id"] for t in snap.get("tabs", [])
                   if t.get("label") in ("pm", "planner") and t["workspace_id"] not in tagged})


def _brief(unit: str, kind: str, project: str, stories: list[str], prs: list[str], scope: str) -> str:
    d = os.path.join(dispatch.state_dir(), "briefs")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%s.md" % unit)
    with open(path, "w") as fh:
        epic_file = ("\n## Your epic file\n%s — your working record (per story: stage, PRs, open threads, waits, "
                     "decisions sent). Read it first; write it at every handoff.\n"
                     % os.path.join(dispatch.state_dir(), "epics", "%s.md" % unit) if kind == "epic" else "")
        fh.write("---\nunit: %s\nkind: %s\nproject: %s\nstories: [%s]\nprs: [%s]\n---\n\n"
                 "# Unit: %s\n\n## Scope\n%s\n\n## Operator-defined behavior\n"
                 "Read each story's Scenarios on Shortcut; they are the behavior. None stated → ask the seat.\n\n"
                 "## Report to\nThe seat, at each gate crossing or blocker (`send.sh --role seat`). Keep this "
                 "workspace's `stage`, `stages`, `stories` and `prs` tokens current.\n%s"
                 % (unit, kind, project, ", ".join(stories), ", ".join(prs), unit, scope, epic_file))
    return path


def create_unit(st: dict, name: str, kind: str, project: str, stories: list[str], prs: list[str],
                scope: str, epic: str | None = None) -> str:
    import units
    brief = _brief(name, kind, project, stories, prs, scope)
    out = units.create(name, kind, project, stories, prs, epic=epic)
    dispatch.enqueue(st, out["pane"], "Read your brief at %s and begin." % brief, unit=name)
    return out["workspace"]


def _subject(ev: dict) -> str:
    return ev.get("pr") or ev.get("story") or ""


def handle(snap: dict, st: dict, events: list[dict], triage_fn=triage, create_fn=None,
           settle_fn=None, stack_fn=pr_stack, lookup_fn=None) -> list[str]:
    """Route matched events, triage the rest, act on the verdict. Returns log lines."""
    log, cache = [], {}
    create_fn = create_fn or create_unit
    lookup_fn = lookup_fn or (lambda st_, ids: lookup_epics(st_, ids))
    pending = dispatch.pending_restore(snap, st)
    lost = _guard_tokens_lost(snap) + sorted(pending)
    only = os.environ.get("PROMETHEUS_FILTER")
    for ev in events:
        if only and ev["kind"] in ("pr", "story") and not re.search(only, ev.get("title") or ev.get("line", "")):
            if ev["kind"] == "pr":  # forget it, so a widened filter later sees it as new
                st["cursors"].pop("pr:" + ev["pr"], None)
            continue  # trial runs act only on matching subjects; nothing is remembered for the rest
        if ev["kind"] == "error":
            log.append(ev["line"])
            continue
        if ev["kind"] == "pr":
            try:
                ev["stack"] = stack_fn(ev["pr"], cache)
            except (RuntimeError, ValueError, KeyError):
                ev["stack"] = [ev["pr"]]
        if ev["kind"] == "story" and ev["state"] in DONE_STATES + DROP_STATES and settle_fn:
            log.append(settle_fn(ev["story"], ev["state"]))
        subject = _subject(ev)
        if subject in st["ignored"]:
            continue
        owner = _imaged_owner(pending, ev)
        if owner:
            # its unit awaits restore: keep the line for that unit's PM instead of re-triaging it
            st.setdefault("restore_backlog", {}).setdefault(owner, []).append(ev["line"])
            log.append("held for restore of %s: %s" % (owner, subject))
            continue
        ev_stories = list(dict.fromkeys(filter(None, [ev.get("story"), *ev.get("stories", [])])))
        hits = dispatch.match_units(snap, ev)
        if not hits and ev_stories:
            try:
                lookup_fn(st, ev_stories)
            except (RuntimeError, ValueError, OSError) as exc:
                log.append("epic lookup failed: %s" % exc)
            epic = epic_of(st, ev_stories)
            if epic:
                ev["epic"], ev["epic_name"] = epic
                hits = [u for u in dispatch.units(snap) if dispatch._tokens(u).get("epic") == epic[0]]
        if len(hits) > 1:
            names = ",".join(dispatch._tokens(u)["unit"] for u in hits)
            _to_seat(snap, st, "[prometheus] conflict: %s is claimed by %s — routing paused; which unit owns it?"
                     % (subject, names))
            log.append("conflict %s" % subject)
            continue
        if hits:
            unit = hits[0]
            label = dispatch._tokens(unit)["unit"]
            if ev["kind"] == "pr":
                for ref in ev.get("stack") or [ev["pr"]]:
                    if ref not in dispatch._csv(dispatch._tokens(unit).get("prs")):
                        _append_token(unit, "prs", ref)
            for sid in ev_stories:
                if sid not in dispatch.token_list(dispatch._tokens(unit), "stories"):
                    _append_token(unit, "stories", sid)
            target = dispatch.route(snap, {"unit": label, "role": "pm"})
            dispatch.enqueue(st, target, ev["line"], details=ev, unit=label)
            continue
        homing = subject in st.get("homing", [])
        if (ev.get("change") != "new" and not homing) or any(p["id"] == subject for p in st["proposals"]):
            continue  # seen before and not in a unit: already triaged (ignored, proposed or declined)
        if ev["kind"] == "story" and ev["state"] in DONE_STATES + DROP_STATES:
            continue
        if ev.get("epic"):
            if homing:
                st["homing"].remove(subject)
            log.append(open_epic(snap, st, ev, ev_stories, lost, create_fn))
            continue
        if epic_units_on():
            log.append(home_once(snap, st, ev, ev_stories))
            continue
        verdict = review_verdict(ev)
        if verdict is None:
            try:
                verdict = triage_fn(ev, snap)
            except (RuntimeError, ValueError) as exc:
                verdict = {"decision": None, "reason": str(exc)[:200]}
        problem = check_verdict(ev, verdict, snap)
        if problem:
            st.setdefault("untriaged", []).append(subject)
            _to_seat(snap, st, "[prometheus] untriaged: %s — %s (%s). Tell me what it is, or ignore it."
                     % (ev["line"].replace("[prometheus] ", ""), problem, verdict.get("reason", "")))
            log.append("untriaged %s: %s" % (subject, problem))
            continue
        log.append(act(snap, st, ev, verdict, lost, create_fn))
    return log


def epic_units_on() -> bool:
    return os.environ.get("PROMETHEUS_EPIC_UNITS", "1") == "1"


def open_epic(snap: dict, st: dict, ev: dict, stories: list[str], lost: list[str], create_fn) -> str:
    """The first event in an epic with no unit opens one — no proposal (operator decision 2026-10-08)."""
    epic_id, epic_name = ev["epic"], ev.get("epic_name", "")
    name = epic_unit_name(epic_id, epic_name)
    project = repo_projects().get(split_ref(ev["pr"])[0]) if ev["kind"] == "pr" else default_project()
    if not project:
        return home_once(snap, st, ev, stories, why="no project for epic %s (set trackers.shortcut.default_project)"
                         % epic_id)
    if lost:
        _to_seat(snap, st, "[prometheus] epic %s (%s) has new work (%s) but units await restore or carry no "
                 "tokens (%s) — opening held" % (epic_name or epic_id, name, _subject(ev), ",".join(lost)))
        return "epic open held %s" % name
    prs = list(ev.get("stack") or ([ev["pr"]] if ev.get("pr") else []))
    review = ev["kind"] == "pr" and ev.get("source") in REVIEW_SOURCES
    scope = ("Epic %s (%s): every story and PR in it is yours — the operator's stories through the full lifecycle, "
             "teammates' PRs through the review loop. Opened by: %s%s."
             % (epic_name or "?", epic_id, ev["line"].replace("[prometheus] ", ""),
                "" if not review else (" (review requested from the operator)" if ev.get("source") == "review-requested"
                                       else " (review not requested: it touches the operator's owned paths — say so "
                                            "in each review body and post COMMENT unless Critical/High stand)")))
    try:
        ws = create_fn(st, name, "epic", project, stories, prs, scope, epic=epic_id)
    except (RuntimeError, ValueError) as exc:
        if ev["kind"] == "pr":
            st["cursors"].pop("pr:" + ev["pr"], None)  # seen again next tick
        _to_seat(snap, st, "[prometheus] could not open epic unit %s: %s — retrying next tick" % (name, str(exc)[:200]))
        return "epic open failed %s: %s" % (name, exc)
    return "opened epic unit %s (%s) for %s" % (name, ws, _subject(ev))


def home_once(snap: dict, st: dict, ev: dict, stories: list[str], why: str | None = None) -> str:
    """No epic (or no story) → the seat, once per subject, to home it; it routes once it has one."""
    subject = _subject(ev)
    asked = st.setdefault("homing", [])
    if subject in asked:
        return "homing pending %s" % subject
    asked.append(subject)
    why = why or ("story %s has no epic" % ", ".join(stories) if stories else "PR has no story")
    _to_seat(snap, st, "[prometheus] needs a home — %s: %s. Home it in an epic (planner or a PM sets it); it "
             "routes to that epic's unit on its next change." % (why, ev["line"].replace("[prometheus] ", "")))
    return "homing %s: %s" % (subject, why)


def _imaged_owner(pending: dict, ev: dict) -> str | None:
    stories = set(filter(None, [ev.get("story"), *ev.get("stories", [])]))
    prs = set(filter(None, [ev.get("pr"), *ev.get("stack", [])]))
    for name, rec in pending.items():
        t = rec.get("tokens", {})
        if stories & set(dispatch.token_list(t, "stories")) or prs & set(dispatch._csv(t.get("prs"))):
            return name
    return None


def _append_token(unit: dict, key: str, value: str) -> None:
    import units
    vals = dispatch._csv(dispatch._tokens(unit).get(key))
    if value not in vals:
        vals.append(value)
        units.tag_workspace(unit["workspace_id"], **{key: ",".join(vals)})
        unit.setdefault("tokens", {})[key] = ",".join(vals)


def _to_seat(snap: dict, st: dict, line: str) -> None:
    try:
        dispatch.enqueue(st, dispatch.route(snap, {"role": "seat"}), line)
    except dispatch.RouteError:
        st.setdefault("seat_backlog", []).append(line)


def act(snap: dict, st: dict, ev: dict, verdict: dict, lost: list[str], create_fn) -> str:
    subject = _subject(ev)
    decision = verdict.get("decision")
    if decision == "ignore":
        st["ignored"].append(subject)
        return "ignore %s: %s" % (subject, verdict.get("reason", ""))
    if decision == "attach":
        unit = next((u for u in dispatch.units(snap) if dispatch._tokens(u).get("unit") == verdict.get("attach_to")), None)
        if not unit:
            return "attach %s: unit %s not found" % (subject, verdict.get("attach_to"))
        _append_token(unit, "prs" if ev["kind"] == "pr" else "stories", subject)
        dispatch.enqueue(st, dispatch.route(snap, {"unit": verdict["attach_to"], "role": "pm"}),
                         ev["line"] + " (attached: %s)" % verdict.get("reason", ""), details=ev,
                         unit=verdict["attach_to"])
        return "attach %s → %s" % (subject, verdict["attach_to"])
    prop = verdict.get("proposal") or {}
    prs = sorted(set(prop.get("prs") or []) | set(ev.get("stack") or []))
    stories = prop.get("stories") or ev.get("stories") or ([ev["story"]] if ev.get("story") else [])
    auto = ev["kind"] == "pr" and ev.get("source") in REVIEW_SOURCES and prop.get("kind") == "review"
    if auto and not lost:
        try:
            return _create_review(st, ev, prop, stories, prs, create_fn)
        except (RuntimeError, ValueError) as exc:
            st["cursors"].pop("pr:" + ev["pr"], None)  # seen again next tick
            _to_seat(snap, st, "[prometheus] could not open the review unit for %s: %s — retrying next tick"
                     % (ev["pr"], str(exc)[:200]))
            return "create failed %s: %s" % (ev["pr"], exc)
    st["next_pid"] = st.get("next_pid", 0) + 1
    pid = "p%d" % st["next_pid"]
    st["proposals"].append({"id": subject, "pid": pid, "kind": prop.get("kind"), "name": prop.get("name"),
                            "project": prop.get("project"), "stories": stories, "prs": prs,
                            "reason": verdict.get("reason", ""), "event": ev.get("line")})
    why = " (auto-create held: %s awaiting restore or carrying no tokens)" % ",".join(lost) if auto else ""
    _to_seat(snap, st, "[prometheus] proposal %s: new %s unit %s for %s — %s%s. Answer with "
             "proposal.sh approve %s | decline %s"
             % (pid, prop.get("kind"), prop.get("name"), ", ".join(prs + stories), verdict.get("reason", ""),
                why, pid, pid))
    return "proposed %s %s" % (pid, prop.get("name"))


def _create_review(st: dict, ev: dict, prop: dict, stories: list[str], prs: list[str], create_fn) -> str:
    why = ("review requested from the operator" if ev.get("source") == "review-requested" else
           "not requested: it touches the operator's owned paths — say so in each review body and post "
           "COMMENT unless Critical/High stand")
    ws = create_fn(st, prop["name"], "review", prop["project"], stories, prs,
                   "Review the stack %s (%s)." % (", ".join(prs), why))
    return "created review unit %s (%s) for %s" % (prop["name"], ws, ", ".join(prs))


def proposal(cmd: str, pid: str) -> str:
    snap = dispatch.snapshot()
    with dispatch.locked_state() as st:
        prop = next((p for p in st["proposals"] if p["pid"] == pid), None)
        if not prop:
            raise ValueError("no proposal %s" % pid)
        st["proposals"].remove(prop)
        if cmd == "decline":
            st["ignored"].append(prop["id"])
            return "declined %s; %s ignored" % (pid, prop["id"])
        ws = create_unit(st, prop["name"], prop["kind"], prop["project"], prop["stories"], prop["prs"],
                         "%s — %s" % (prop["event"], prop["reason"]))
        return "approved %s: unit %s (%s)" % (pid, prop["name"], ws)


# ------------------------------------------------------------------- settle

def settle(story: str, state: str) -> str:
    kb = os.path.join(LIB, "kb.py")
    out = subprocess.run([sys.executable, kb, "inbox", "settle", "--story", story, "--state", state],
                         capture_output=True, text=True, timeout=60)
    msg = (out.stdout or out.stderr).strip()
    return "settle %s: %s" % (story, msg or "rc=%d" % out.returncode)


# ------------------------------------------------------------------- health

def health(snap: dict, st: dict, now: float | None = None) -> list[str]:
    """Remember each lead's session; resume a lead whose pane is gone or whose agent exited."""
    import units
    now = now or time.time()
    sessions = st.setdefault("sessions", {})
    log = []
    for u in dispatch.units(snap):
        label = dispatch._tokens(u)["unit"]
        lead = dispatch.lead_role(u)
        panes = dispatch.panes_with_role(snap, lead, u["workspace_id"])
        live = [p for p in panes if p.get("agent")]
        if live:
            sid = (live[0].get("agent_session") or {}).get("value")
            if sid:
                sessions[label] = sid
            continue
        sid = sessions.get(label)
        last = st.setdefault("restarts", {}).get(label, 0)
        if not sid or now - last < HEALTH_COOLDOWN:
            continue
        st["restarts"][label] = int(now)
        if panes:
            units.start(panes[0]["pane_id"], lead, lead, claude_args=["--resume", sid])
            log.append("resumed %s in %s (session %s)" % (lead, panes[0]["pane_id"], sid))
        else:
            pane = units.open_tab(u["workspace_id"], lead, lead, claude_args=["--resume", sid])
            log.append("reopened %s for %s in %s (session %s)" % (lead, label, pane, sid))
        _to_seat(snap, st, "[prometheus] %s of %s had exited; resumed session %s" % (lead, label, sid))
    for p in dispatch.panes_with_role(snap, "librarian"):
        last = st.setdefault("restarts", {}).get("librarian", 0)
        if p.get("agent") or now - last < HEALTH_COOLDOWN:
            continue
        st["restarts"]["librarian"] = int(now)
        units.start(p["pane_id"], "librarian", "librarian")  # stateless: always fresh
        log.append("restarted librarian in %s" % p["pane_id"])
    return log


# --------------------------------------------------------------------- tick

def tick(snap: dict, st: dict) -> list[str]:
    events, log = [], []
    try:
        for line in poll_owned(st):
            _to_seat(snap, st, line)
    except (RuntimeError, ValueError, OSError) as exc:
        log.append("poll_owned failed: %s" % exc)
    for source in (poll_github, poll_shortcut):
        try:
            events += source(snap, st)
        except (RuntimeError, ValueError, OSError) as exc:
            log.append("%s failed: %s" % (source.__name__, exc))
    log += handle(snap, st, events, settle_fn=settle)
    log += health(snap, st)
    return log


# ---------------------------------------------------------------------- CLI

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="events.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("poll-github")
    sub.add_parser("poll-shortcut")
    s = sub.add_parser("pr-stack")
    s.add_argument("repo")
    s.add_argument("number")
    m = sub.add_parser("match")
    m.add_argument("event")
    t = sub.add_parser("triage")
    t.add_argument("event")
    sub.add_parser("health")
    p = sub.add_parser("proposal")
    p.add_argument("action", choices=["approve", "decline"])
    p.add_argument("pid")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "pr-stack":
            print("\n".join(pr_stack(pr_ref(a.repo, a.number))))
            return 0
        if a.cmd == "proposal":
            print(proposal(a.action, a.pid))
            dispatch.poke()
            return 0
        snap = dispatch.snapshot()
        if a.cmd == "match":
            hits = dispatch.match_units(snap, json.loads(a.event))
            if len(hits) > 1:
                print("CONFLICT")
            elif hits:
                print(hits[0]["workspace_id"])
            return 0
        if a.cmd == "triage":
            print(json.dumps(triage(json.loads(a.event), snap)))
            return 0
        with dispatch.locked_state() as st:
            if a.cmd == "poll-github":
                rows = poll_github(snap, st)
            elif a.cmd == "poll-shortcut":
                st["cursors"].pop("shortcut:polled", None)
                rows = poll_shortcut(snap, st)
            else:
                rows = [{"line": l} for l in health(snap, st)]
        for r in rows:
            print(json.dumps(r))
    except (RuntimeError, ValueError) as exc:
        print("events: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
