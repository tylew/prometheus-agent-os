# prometheus

Role-based delivery hierarchy on Herdr. Design: `docs/specs/workspace/prometheus/design.md`, amended by
`docs/specs/workspace/prometheus-unit-engine/design.md` (questions stay in the session that has them, the
IDR replaces design and plan, one validator question ends a story, the unit engine).

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
  ├─ tab pm                 project-manager — owns the epic; never carries an operator question
  ├─ tab plan-sc-<id>    one story to Ready (research, BDD spec, definition of ready); asks in its own tab
  ├─ tab plan-<slug>    discovery: a goal into preliminary issues
  ├─ tab impl-sc-<id>       implementor — analysis, the IDR, failing tests first, code; stops, never asks
  ├─ tab review-idr-sc-<id> reviewer — the IDR checked against the story before any code
  ├─ tab review-<pr>        reviewer, fresh per round
  ├─ tab validator-sc-<id>  local dev, the walk, ONE question (Verified, merge · hold · Not as intended), the merge
  └─ tab closeout-sc-<id>   vantage /session-closeout: the IDR and the story's rulings into the planning vault
```

Every tab runs `lib/launch.sh <role>`: resolves `$WORKSPACE`, sets `PROMETHEUS_ROLE`, merges
`templates/settings/launch.json` with the role's file and its `extends` bases (lists add up), writes the
role's MCP config (`--strict-mcp-config`), appends `templates/operator.md` to the system prompt, and adds
`--permission-mode dontAsk` for implementor, reviewer and librarian (`--chrome` for reviewer, planner and
validator). `launch.sh closeout` is the exception: vantage's own session from a detached worktree of the
registered `voltus-custom-skills-hub` clone at `origin/main`, with no prometheus settings.

## Roles

- **Seat** — knows the operator. Triages instruction gaps: operator sign-off, or straight to a
  configurator. Places work that belongs to no epic. Only role that opens runners and configurators.
- **PM** — one epic end to end: the operator's stories through ready → design (IDR) → implement → review →
  validate; teammates' PRs through the review loop. Opens and closes its own tabs; runs review and
  implementation concurrently; relays IDRs, stops and done reports. **Never carries an operator question
  or sends one to the seat**: behavior, scope and UI questions go to the story's planner, merge-or-not to
  the validator. Working record: the epic file `<state>/epics/<unit>.md`. Knows the operator.
- **Planner** — the only story author. Researches current behavior first through three independent
  background subagents (code at `origin/<default>`, the running UI in Chrome, the KB / planning vault /
  Shortcut / meetings / data), then drafts the story in vantage's BDD voice and takes it to the definition of
  ready (one readiness comment, Ready for Development). Asks the operator **in its own tab**; its dialog holds
  only itself. Answers the story's stops.
- **Implementor** — drives one Ready story: four analysis subagents (call chains, behavior at depth, seams
  and tests, contracts and owners), then the IDR and its failure modes before any code (`lib/idr.py` checks
  the IDR), then per rung its own failing tests (one per scenario carrying its `Scenario:` line, one per
  failure mode), builder subagents for the code, a read of each diff against the IDR, the registry's
  validation with `VOLTUS=<worktree>`, the build proof, draft PRs with a scenario-tests table and the IDR on
  the bottom PR. On a voltus-kanban Stop trigger it stops (`report.sh --stopped`) — never asks, never
  guesses.
- **Builder** — a background subagent of the implementor, one rung or fix at a time: a skeleton (names and
  signatures, no behavior) or the code that makes the committed tests pass. `hooks/builder-guard.py` keeps
  it off test files, the IDR, the failure modes and git writes; it returns a report or a stop block.
- **Reviewer** — one round, fresh session; the IDR is its context (held to decision by decision); also the
  IDR check before code.
- **Validator** — ends a story once our review gate is clean and a teammate approved: local dev on the top
  rung, the scenarios walked in Chrome, one question in its own tab, the criteria ticked, the gate re-read
  and the stack merged bottom-up (`--squash --match-head-commit`), then the closeout. Merges a teammate's PR
  only when the operator asks by name.
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

## Questions — where they wait

A question blocks only the session that has it: a planner (behavior, scope, UI, stack-or-fresh) or a
validator (merge or not), each in its own tab — answered there or from the map's preview (`i`). Implementors
stop instead of asking; reviewers never ask; the PM and the seat carry none. Nothing else in the epic waits.

## The IDR

One per story, replacing `design.md` / `plan.md`: voltus-kanban's shape and budget (Approach, Decisions,
Where the scenarios are tested, Rollout and observability; ≤400 words). Written by the implementor before
any code at `<state>/engine/stories/<sc-id>/idr.md`, checked by a reviewer round, carried collapsed on the
stack's bottom PR, and landed at Completed in the team planning vault
(`teams/b-team/vault/02-architecture/`) by vantage's own `/session-closeout`, with decision notes for the
story's human rulings only. Prometheus agents never write the planning repo.

## The build proof

`lib/proof.py run` checks a story's stack from git, so no claim rests on the implementor's word: every commit
is a skeleton, tests or code commit, never tests and code together; each test a tests commit adds fails at
that commit inside its body (the skeleton keeps it from failing at import) and passes at the rung's head;
every story scenario has its `Scenario:` test; every failure mode names a test that exists or says why it
cannot happen. It runs only the named tests, in throwaway detached worktrees, with each package's registry
`scenario_run`. `report.sh --done` refuses without a clean `proof.json` whose rung heads are current; the
reviewer reads it, and a `held before` test with no reason is High.

## The unit engine

`lib/unit_engine.py`, run by the dispatcher on full ticks, takes the PM's mechanical duties over one at a
time. Per unit: `engine.sh on <unit>` puts it in **shadow** — it tracks each story's stage and wait, reads
the agents' reports (`report.sh --stopped|--idr|--done`), copies every unit message to the unit's feed
(`engine.sh feed <unit>`, also under the epic's agent list on the map) and records what it would do,
counting a match each time the PM does the same (`engine.sh status`). A duty acts only once listed:
`engine.sh act <unit> <duty,…>`. Shortcut writes go through `lib/tracker.py` (REST when a token verifies,
else MCP; every write read back).

## Outward

- Every outward post ends with the signature: `⚡ Prometheus by instruction of <operator>`
  (`.claude/prometheus/workspace.json` → `operator`).
- Reviewers post their own rounds; the event follows the counts (approve only on a clean gate,
  request-changes while critical/high stand; on the operator's own PRs a COMMENT that states the event the
  counts give).
- Merges: only the validator, only after the operator's "Verified, merge" in its tab, only squash at the
  walked heads, never `--admin`.
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

Layout + phase status: the design's *File layout*. Self-contained: no other plugin is installed — the
closeout loads vantage from the registered skills-hub clone per launch.
