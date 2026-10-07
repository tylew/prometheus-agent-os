# Creating a story — planner only

Body: `templates/story.md` (leaf) or `templates/story-parent.md`; standard and confirm flow → `stories`.
Create only what the operator confirmed; never advance past `backlog_state`.

## 1. Type — by reality

`bug` = exists and misbehaves · `feature` = does not exist yet (missing UI is a feature) · `chore` = no
user-facing change. "X is missing" is not a bug. Valid set: config `story_types`.

## 2. Epic — required

- General fix / improvement → config `catch_all_epic.id`. `null` → ask the operator; never guess.
- Part of an initiative → find its epic live with `mcp__shortcut__epics-search` (epics churn; no cache).
- None fits → propose one; `epics-create` only on the operator's go-ahead.

## 3. Create

`mcp__shortcut__stories-create` with `name`, `type`, `description`, `epic`, `team`, `owner`,
`workflow_state_id` = id of config `workflow.intake`.

**Parameter traps — exact names only:**

| Tool | Keys | Trap |
|---|---|---|
| `stories-create` | `epic` (number), `team` (id/name/mention), `owner` (user id), `workflow_state_id` (number) | camelCase (`epicId`, `teamId`) is dropped or rejected. **`estimate` is not a key** — passing it fails the whole call with `unrecognized_keys`; nothing is created |
| `stories-update` | `storyPublicId`, `epic` (number), **`team_id`** (UUID — not `team`), `owner_ids` (array), `estimate`, `workflow_state_id`, `labels` (`[{name}]`, full set) | accepts `estimate`; differs from create on team and owner |

## 4. Estimate

Follow-up `stories-update` with `estimate` from config `estimate_scale` (1 · 2 · 3 · 5 · 8). A right-sizing
gate, not a forecast: target ≤ 5; at `split_at` (8) → split. Size moves with code surface, new vs reused
pattern, shared-library fan-out, migration, test/validation load, blockers. The PM re-checks it at
`ready_for_development` against the settled design; a re-check landing on 8 comes back here to split.

## 5. Verify

`stories-get-by-id`: `epic_id`, `team_id`, `workflow_state_id`, owner, `estimate` all held. Fix nulls with
`stories-update`, re-fetch. Record the id in the draft's frontmatter; report as an embedded link.

## Sub-issues (parent + children)

More than 5 scenarios, or an 8 → parent (`templates/story-parent.md`) + one child per work unit, each its
own story ≤ 5 with its own PR. Creating and linking is an outward write — operator confirms first.

- **Create each child with `stories-create`, then link with `stories-add-subtask`**
  (`parentStoryPublicId`, `subTaskPublicId`). Never `stories-create-subtask`: it takes only `name` +
  `description`, so the child lands unhomed, mistyped, in the default state — silently.
- Verify: parent's `sub_task_story_ids`, each child's `parent_story_id`.
- A PR references the child it delivers, never the parent.

