---
name: tracker
description: "Shortcut story operations: who may write which part of a story, workflow states by key and the gate each one needs, the few cases that warrant a permanent comment, PR ↔ story linking and its repair, story creation mechanics (MCP parameter traps, epic homing, estimate, sub-issues). Reached through MCP tools only."
---

# tracker

How a story is written to and moved on the board. The story body standard lives in `stories`.

## Config — read, never recall

```bash
python3 "$CLAUDE_PLUGIN_ROOT/lib/registry.py" tracker --key <project>
```

→ `kind`, `org_slug`, `team_id`, `team_name`, `workflow.{id,intake,states[{key,id,name,gate}]}`, `labels`,
`story_types`, `estimate_scale`, `split_at`, `catch_all_epic`, `docs_folder`. Name a state by its **key**
(`backlog_state`, `ready_for_development`, …); resolve the id from `workflow.states` at write time. Never
hardcode an id, display name, team or org.

**No board** — `kind: operator`, or `null` (no `tracker.ref`): every outward write short-circuits to an
operator gate. Say what would have been posted; the operator decides. State moves do not exist.

## Who writes what

| Writer | May write | Never |
|---|---|---|
| `planner` | creates stories (Backlog, typed, epic homed, owner, estimate) and sub-issues; the whole description; the readiness comment; the move to Ready for Development; clearing `blocked` once a stop is settled | advance past Ready for Development |
| `project-manager` | state at each gate after Ready; estimate re-check; the `question` / `blocked` labels; relations; the five comment cases | create a story; edit Scenarios or acceptance criteria text — a change goes to the planner; tick a criterion |
| validator | AC ticks and the screenshots `<details>` on a Verified walk; Completed after the top rung merges when the integration did not move it (`validate` §5–§6) | anything else on the board |
| implementor | nothing (allow-lists deny it) | — |

## Always

- **MCP only** — `mcp__shortcut__*`. The REST token 401s; never curl. Tools not loaded → ToolSearch
  `select:mcp__shortcut__…`. Server disconnected → the operator reconnects via `/mcp`.
- **Story id is a number** — `storyPublicId: 12345`, no `sc-` prefix.
- **Send only the fields that change.** `labels` replaces the whole set — send the full live list as
  `[{name}]`. `description` replaces the whole body — rebuild it from the live copy.
- **Pre-write guard** before any `description` write: `stories-get-by-id`; `updated_at` moved since your
  read, or a box ticked → re-read, re-merge, then write.
- **Re-read after every write** with `stories-get-by-id` — never `stories-search` (its index lags by
  seconds). "Created/Updated story" returns even when a field was silently dropped; check each field held.
- **Embedded links in user-facing text**: `[sc-#####](https://app.shortcut.com/<org_slug>/story/#####)`.
  Branch names and commit messages keep the bare key. Never `sc-#####` in a story or PR title.
- **One story, one team** — the config's `team_id`. Cross-team epics are normal; never move a story to
  match its epic.

## States and gates (PM)

Move: `mcp__shortcut__stories-update` with `storyPublicId` + `workflow_state_id` (snake_case number).

| Gate met | → key |
|---|---|
| created (intake) | `backlog_state` (planner, at create) |
| design posted; the type's readiness bar met ([board.md](references/board.md) → Readiness) | `ready_for_development` |
| queued to work next — ready stories only, none with an unresolved *blocked by* | `on_deck` |
| worktree created after plan confirmation, or draft PR up | `in_development` |
| PR un-drafted | `ready_for_review` |
| PR merged to `main` | `completed` |
| decided against | `won_t_fix` |

`triage` / `needs_further_scoping` hold intake with a gap too early to estimate.

- **At the gate, in the same action** — never batched, never stale. "Start / pick up" alone moves nothing.
- **`ready_for_review` ⇔ non-draft PR.** They move together; re-draft → back to `in_development`. Un-draft
  mechanics → `branching`.
- **Re-assert after un-draft.** The GitHub integration moves a story linked from a draft PR to
  `in_development` (correct; leave it). On un-draft, set `ready_for_review` after the integration's event
  lands, then re-read — automation can land after your write.
- **ACs are ticked by the validator** (`validate` §5): `- [ ]` → `- [x]` for each
  criterion a Verified walk passed; full `description` resent, re-read. Never `completed` with an
  unchecked box: unchecked = not done (another walk), or the criterion is wrong → planner revises it. A criterion
  only a deployed env can show is ticked at merge from the evidence that stands in for it, and what was
  not seen is named.
- **Done = `completed` = merged to `main`.** The merge is the last board gate; a merged PR whose story is
  not `completed` is drift. Deploy, post-deploy checks and reverts move no story; a defect after merge is
  a new story.
- **Regress honestly** — review sends work back → move it back. Comment only if scope/AC moved.
- **Unsure a gate is met** → advance conservatively and say so; never leave it stale.
- **`question` label ⇔ a *Still open* item says "Blocks this story".** Re-check on every move and
  description write. Never `ready_for_development` with it on.

## Board hygiene, comments, PR linking, readiness

[references/board.md](references/board.md) — read before any description or comment write.

## Creating a story (planner)

[references/create.md](references/create.md) — MCP parameter traps, type, epic, estimate, sub-issues.
