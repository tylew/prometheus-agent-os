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
             "headRefOid,reviewDecision,latestReviews,comments,statusCheckRollup,url")
DONE_STATES = ("Completed",)
DROP_STATES = ("Won't Fix",)
HEALTH_COOLDOWN = 600
NEW_PER_TICK = int(os.environ.get("PROMETHEUS_NEW_PER_TICK", 3))


def run(cmd: list[str], timeout: int = 120, cwd: str | None = None, stdin: str | None = None) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
                         input=stdin if stdin is not None else "")
    if out.returncode != 0:
        raise RuntimeError("%s: %s" % (" ".join(cmd[:3]), (out.stderr or out.stdout).strip()[:300]))
    return out.stdout


def gh_json(*args: str):
    return json.loads(run([os.environ.get("GH_BIN", "gh"), *args]) or "null")


# ------------------------------------------------------------------- GitHub

def pr_ref(repo: str, number) -> str:
    return "%s#%s" % (repo, number)


def split_ref(ref: str) -> tuple[str, str]:
    repo, num = ref.rsplit("#", 1)
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


def fingerprint(pr: dict) -> dict:
    reviews = pr.get("latestReviews") or []
    last = max(reviews, key=lambda r: r.get("submittedAt") or "", default={})
    state = "merged" if pr.get("mergedAt") else (pr.get("state") or "").lower()
    return {"state": state, "draft": bool(pr.get("isDraft")), "head": pr.get("headRefOid"),
            "ci": ci_state(pr.get("statusCheckRollup")), "decision": pr.get("reviewDecision") or "",
            "review": "%s:%s" % (last.get("author", {}).get("login", ""), last.get("state", "")) if last else "",
            "review_at": last.get("submittedAt", ""), "comments": len(pr.get("comments") or [])}


def pr_changes(ref: str, old: dict | None, new: dict) -> list[str]:
    """Only changes that alter someone's next move."""
    if old is None:
        return ["new"]
    out = []
    if new["state"] != old["state"] and new["state"] in ("merged", "closed"):
        out.append(new["state"])
    if new["ci"] != old["ci"] and new["ci"] in ("pass", "fail"):
        out.append("ci %s" % new["ci"])
    if new["review_at"] != old["review_at"] and new["review"]:
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


def view_pr(ref: str) -> dict:
    repo, num = split_ref(ref)
    return gh_json("pr", "view", num, "-R", repo, "--json", PR_FIELDS)


def poll_github(snap: dict, st: dict) -> list[dict]:
    repos = watched_repos()
    if not repos:
        raise RuntimeError("no watched repos (registry or PROMETHEUS_REPOS); GitHub not polled")
    review = set(search_prs("--review-requested=@me", repos))
    authored = set(search_prs("--author=@me", repos))
    held = {r for u in dispatch.units(snap) for r in dispatch._csv(dispatch._tokens(u).get("prs"))}
    events, fresh = [], 0
    for ref in sorted(review | authored | held):
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
        new = fingerprint(pr)
        st["cursors"][key] = new
        for change in pr_changes(ref, old, new):
            if change == "new" and ref in held:
                continue
            events.append({
                "kind": "pr", "pr": ref, "change": change, "title": pr.get("title", ""),
                "stories": stories_in(pr.get("title"), pr.get("body"), pr.get("headRefName")),
                "source": "review-requested" if ref in review else ("authored" if ref in authored else "unit"),
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
                       "updated_at": {"type": "string"}}}}},
}


SHORTCUT_READ_TOOLS = ["mcp__shortcut__users-get-current", "mcp__shortcut__stories-search",
                       "mcp__shortcut__stories-get-by-id", "mcp__shortcut__epics-get-by-id",
                       "mcp__shortcut__workflows-get-by-id", "mcp__shortcut__workflows-get-default"]


def claude_json(prompt: str, schema: dict, *, agent: str | None = None, mcp: dict | None = None,
                allowed: list[str] | None = None, model: str = "haiku", timeout: int = 180) -> dict:
    """One-shot claude -p with structured output, outside the workspace so no CLAUDE.md loads."""
    cmd = [os.environ.get("CLAUDE_BIN", "claude"), "-p", "--model", model, "--output-format", "json",
           "--json-schema", json.dumps(schema),
           "--settings", os.path.join(PLUGIN, "templates", "settings", "launch.json"),
           "--max-budget-usd", os.environ.get("PROMETHEUS_ONESHOT_BUDGET", "0.25")]
    if agent:
        cmd += ["--plugin-dir", PLUGIN, "--agent", agent]
    if mcp is not None:
        cfg = os.path.join(dispatch.state_dir(), "mcp-oneshot.json")
        with open(cfg, "w") as fh:
            json.dump({"mcpServers": mcp}, fh)
        cmd += ["--strict-mcp-config", "--mcp-config", cfg]
    else:
        cmd += ["--strict-mcp-config"]
    if allowed:
        cmd += ["--allowed-tools", ",".join(allowed)]
    # prompt on stdin: --mcp-config is variadic and would swallow a positional prompt
    out = json.loads(run(cmd, timeout=timeout, cwd=tempfile.gettempdir(), stdin=prompt))
    if out.get("permission_denials"):
        denied = sorted({d.get("tool_name", "?") for d in out["permission_denials"]})
        raise RuntimeError("claude -p denied %s; its answer is not trusted" % ", ".join(denied))
    if out.get("is_error") or "structured_output" not in out:
        raise RuntimeError("claude -p: %s" % str(out.get("result"))[:300])
    return out["structured_output"]


def poll_shortcut(snap: dict, st: dict, now: float | None = None) -> list[dict]:
    now = now or time.time()
    every = int(os.environ.get("SHORTCUT_INTERVAL", 300))
    if now - st["cursors"].get("shortcut:polled", 0) < every:
        return []
    since = st["cursors"].get("shortcut:since") or time.strftime("%Y-%m-%d", time.gmtime(now - 7 * 86400))
    held = {s for u in dispatch.units(snap) for s in dispatch._csv(dispatch._tokens(u).get("stories"))}
    prompt = ("Using only the Shortcut MCP tools: list stories owned by the current user that were updated "
              "on or after %s, plus these stories regardless of owner: %s. Return id as sc-<number>, name, "
              "workflow state name, epic name, updated_at. Read only; change nothing."
              % (since, ", ".join(sorted(held)) or "none"))
    mcp = {"shortcut": {"type": "http", "url": os.environ.get("SHORTCUT_MCP_URL", "https://mcp.shortcut.com/mcp")}}
    result = claude_json(prompt, SHORTCUT_SCHEMA, mcp=mcp, allowed=SHORTCUT_READ_TOOLS)
    st["cursors"]["shortcut:polled"] = int(now)
    st["cursors"]["shortcut:since"] = time.strftime("%Y-%m-%d", time.gmtime(now))
    events, fresh = [], 0
    for s in result.get("stories", []):
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
               "naming": {"story": "sc-<id>-<slug>", "story-set": "<theme-slug>", "planning": "plan-<slug>",
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
        fh.write("---\nunit: %s\nkind: %s\nproject: %s\nstories: [%s]\nprs: [%s]\n---\n\n"
                 "# Unit: %s\n\n## Scope\n%s\n\n## Operator-defined behavior\n"
                 "Read each story's Scenarios on Shortcut; they are the behavior. None stated → ask the seat.\n\n"
                 "## Report to\nThe seat, at each gate crossing or blocker (`send.sh --role seat`). Keep this "
                 "workspace's `stage`, `stories` and `prs` tokens current.\n"
                 % (unit, kind, project, ", ".join(stories), ", ".join(prs), unit, scope))
    return path


def create_unit(st: dict, name: str, kind: str, project: str, stories: list[str], prs: list[str],
                scope: str) -> str:
    import units
    brief = _brief(name, kind, project, stories, prs, scope)
    out = units.create(name, kind, project, stories, prs)
    dispatch.enqueue(st, out["pane"], "Read your brief at %s and begin." % brief, unit=name)
    return out["workspace"]


def _subject(ev: dict) -> str:
    return ev.get("pr") or ev.get("story") or ""


def handle(snap: dict, st: dict, events: list[dict], triage_fn=triage, create_fn=create_unit,
           settle_fn=None, stack_fn=pr_stack) -> list[str]:
    """Route matched events, triage the rest, act on the verdict. Returns log lines."""
    log, cache = [], {}
    lost = _guard_tokens_lost(snap)
    for ev in events:
        if ev["kind"] == "error":
            log.append(ev["line"])
            continue
        if ev["kind"] == "pr":
            try:
                ev["stack"] = stack_fn(ev["pr"], cache)
            except (RuntimeError, ValueError, KeyError):
                ev["stack"] = [ev["pr"]]
        if ev["kind"] == "story" and ev["state"] in DONE_STATES + DROP_STATES and settle_fn:
            log.append(settle_fn(ev["story"]))
        subject = _subject(ev)
        if subject in st["ignored"]:
            continue
        hits = dispatch.match_units(snap, ev)
        if len(hits) > 1:
            names = ",".join(dispatch._tokens(u)["unit"] for u in hits)
            _to_seat(snap, st, "[prometheus] conflict: %s is claimed by %s — routing paused; which unit owns it?"
                     % (subject, names))
            log.append("conflict %s" % subject)
            continue
        if hits:
            unit = hits[0]
            label = dispatch._tokens(unit)["unit"]
            if ev["kind"] == "pr" and ev["pr"] not in dispatch._csv(dispatch._tokens(unit).get("prs")):
                _append_token(unit, "prs", ev["pr"])
            target = dispatch.route(snap, {"unit": label, "role": "pm"})
            dispatch.enqueue(st, target, ev["line"], details=ev, unit=label)
            continue
        if ev.get("change") != "new" or any(p["id"] == subject for p in st["proposals"]):
            continue  # seen before and not in a unit: already triaged (ignored, proposed or declined)
        if ev["kind"] == "story" and ev["state"] in DONE_STATES + DROP_STATES:
            continue
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
    auto = ev["kind"] == "pr" and ev.get("source") == "review-requested" and prop.get("kind") == "review"
    if auto and not lost:
        ws = create_fn(st, prop["name"], "review", prop["project"], stories, prs,
                       "Review the stack %s (review requested from the operator). %s"
                       % (", ".join(prs), verdict.get("reason", "")))
        return "created review unit %s (%s) for %s" % (prop["name"], ws, ", ".join(prs))
    st["next_pid"] = st.get("next_pid", 0) + 1
    pid = "p%d" % st["next_pid"]
    st["proposals"].append({"id": subject, "pid": pid, "kind": prop.get("kind"), "name": prop.get("name"),
                            "project": prop.get("project"), "stories": stories, "prs": prs,
                            "reason": verdict.get("reason", ""), "event": ev.get("line")})
    why = " (auto-create held: workspaces %s look like units but carry no tokens)" % ",".join(lost) if auto else ""
    _to_seat(snap, st, "[prometheus] proposal %s: new %s unit %s for %s — %s%s. Answer with "
             "proposal.sh approve %s | decline %s"
             % (pid, prop.get("kind"), prop.get("name"), ", ".join(prs + stories), verdict.get("reason", ""),
                why, pid, pid))
    return "proposed %s %s" % (pid, prop.get("name"))


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

def settle(story: str) -> str:
    kb = os.path.join(LIB, "kb.py")
    out = subprocess.run([sys.executable, kb, "inbox", "settle", "--story", story],
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
            units._h("pane", "run", panes[0]["pane_id"], units._launch_cmd(lead, claude_args=["--resume", sid]))
            log.append("resumed %s in %s (session %s)" % (lead, panes[0]["pane_id"], sid))
        else:
            pane = units.open_tab(u["workspace_id"], lead, lead, claude_args=["--resume", sid])
            log.append("reopened %s for %s in %s (session %s)" % (lead, label, pane, sid))
        _to_seat(snap, st, "[prometheus] %s of %s had exited; resumed session %s" % (lead, label, sid))
    return log


# --------------------------------------------------------------------- tick

def tick(snap: dict, st: dict) -> list[str]:
    events, log = [], []
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
