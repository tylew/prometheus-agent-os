# prometheus

Role-based delivery hierarchy on Herdr. Design:
`docs/specs/workspace/prometheus/design.md`.

**Inactive by default.** Not in `enabledPlugins`, not in the marketplace. Loads only per launch:

```sh
plugins/prometheus/lib/launch.sh seat
```

Then say **begin** (`/prometheus:begin`) to start the dispatcher.

## Layout (Herdr)

```
control workspace "Prometheus" (operator)
  ├─ tab seat             orchestrator — the operator's interface; triages, routes, decides what needs the operator
  ├─ tab librarian        the operator's direct line to the KB writer (never messaged by agents)
  ├─ tab map              live view of every epic, agent and PR
  ├─ tab dispatcher       script, not an agent — the only watcher
  └─ runner / configurator tabs, opened by the seat only
epic workspace "epic-<id>-<slug>" (one per epic)
  ├─ tab pm               project-manager — owns the epic; the only agent the seat addresses
  ├─ tab planner          writes the epic's stories
  ├─ tab impl-<item>      implementor, fresh per work item, started in its worktree
  ├─ tab review-<pr>      reviewer, fresh per round
  └─ tab validate-<pr>    walks the scenarios on local dev in Chrome
```

Every tab runs `lib/launch.sh <role>`: resolves `$WORKSPACE`, sets `PROMETHEUS_ROLE`, merges
`templates/settings/launch.json` with the role's file and its `extends` bases (lists add up), writes the
role's MCP config (`--strict-mcp-config`), appends `templates/operator.md` to the system prompt, and adds
`--permission-mode dontAsk` for implementor, reviewer and librarian.

## Roles

- **Seat** — knows the operator. Triages instruction gaps: operator sign-off, or straight to a
  configurator. Places work that belongs to no epic. Only role that opens runners and configurators.
- **PM** — one epic end to end: the operator's stories through triage → design → plan → implement →
  review → merge-ready; teammates' PRs through the review loop. Opens and closes its own tabs; runs review
  and implementation concurrently. Working record: the epic file `<state>/epics/<unit>.md`, so a
  `/compact` or a fresh session loses nothing. Knows the operator.
- **Planner · implementor · reviewer** — full sessions in their own tabs; report only to their PM. Know an
  operator exists beyond their reach, not who.
- **Librarian** — the only KB writer (`docs/kb/` through `kb.sh`). A PM or the seat starts it as a
  background subagent (`prometheus:librarian`) per decision batch; its final message is the answer. Its
  tab is for the operator alone.
- **Runner** — quick work; files only, one tab per item.
- **Configurator** — the only role that edits this plugin or `.claude/prometheus/`
  (`hooks/project-guard.py` enforces it). Negotiates acceptance criteria with the seat first; validates
  in tiers: unit tests + `lib/lint.py` → `lib/probes.py` → `lib/e2e.py` → a full dry run on request.
  Gaps route up: worker → PM → seat.

## How work arrives

The dispatcher polls GitHub, Shortcut and every agent pane each interval (woken at once by `send.sh`).
A change is routed by story / PR token to the unit holding it; otherwise by the story's epic: the epic's
unit, or a new epic unit opened automatically with a briefed PM. A story with no epic goes to the seat
once.

Review triggers: a review requested of the operator by name, or a teammate's PR touching the operator's
`owned_paths` (watched repos only — the registry's). PRs already open at the first poll are listed to the
seat, never auto-reviewed.

Dropped: changes that alter no one's next move, bot and tool comments, and prometheus's own posts (signed,
or body-less thread-reply reviews from the operator's account). Delivery waits for a safe pane state and
coalesces lines.

## Outward

- Every outward post ends with the signature: `⚡ Prometheus by instruction of <operator>`
  (`.claude/prometheus/workspace.json` → `operator`).
- Reviewers post their own rounds; the event follows the counts (approve only on a clean gate,
  request-changes while critical/high stand).
- Access per role: write tools denied except to their writer; the PM changes LaunchDarkly flags only
  through a per-call prompt; Redash is read-only through `skills/data/scripts/redash.sh`.

## Recovery

The dispatcher keeps a restore image of every unit. After a Herdr restart, **begin** restores each unit
on its previous Claude sessions. State: `~/.local/state/prometheus` (`dispatch.json`, epic files, settings,
MCP configs). Registry: `.claude/prometheus/`. This plugin is its own git repo.

**Trial period:** the workspace `CLAUDE.md` still loads and names voltus-besstie skills. Prometheus agents follow
their own instructions for role behavior; the workspace file is rewritten at cutover.
Ownership + stage are Herdr tokens; each agent's context is its Claude session.

**Icons:** the map draws agent logos and state marks from the bundled "Herdr Agent Icons Max" font
(`assets/fonts/`, MIT, from herdr-radar). The map installs it per user on first run and uses it from the
next start; `python3 lib/map/icons.py install` installs it now. `PROMETHEUS_MAP_ICONS=text` keeps plain
symbols.

Layout + phase status: the design's *File layout*. Self-contained: no other plugin is required.
