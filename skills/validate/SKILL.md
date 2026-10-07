---
name: validate
description: "Operator-in-the-loop manual validation of a unit's change on local dev, and bringing local dev up for it. The project manager proves the served tree, builds a checklist (one item per Then clause of the operator's scenarios, the PR's manual steps, the diff's user-visible surface), walks it one item at a time (confirm / reject / note) in place or through the seat, captures evidence on a rejection, records verdicts in the unit's spec dir, and turns a rejection into a fix brief. Use to validate, QA, walk scenarios or sign off a PR before merge or deploy, and to bring up / start / run a project locally."
---

# validate — the operator is the instrument

Run by the `project-manager` only. Implementors and reviewers never validate: they cannot ask a human.

Only the operator's answer satisfies an item. Code reading, a curl probe, a green suite, a screenshot the
agent interprets — evidence for building the checklist, never a verdict. Scope is **visual** (copy, labels,
tooltips, badges, states, layout) **and functional** (what an action does, persists, shows after reload,
refreshes without one); label every item with its kind.

## 0. Local dev, proven

- Bare "dev" is ambiguous: local dev vs the deployed env (`registry.py field deploy.envs --key <project>`).
  Ask, one sentence, options as choices. Deployed → not this skill.
- Bring-up and the served-tree proof: `references/dev-up.md`. Not up, or up on another branch → bring it up
  first. Never restart pieces mid-walk: answered items are invalidated.
- Opening message states branch, sha and both probes (a symbol the branch adds, one it removes), then the walk
  starts.

## 1. Build the whole checklist before the first question

Sources, earlier owns the wording on conflict:

1. **The unit's Gherkin scenarios** (operator-defined; `stories`). One item per `Then` / `But` clause; its
   `Given`s are setup, its `When` the action, the clause the pass condition — copied, not re-derived. A
   `Scenario Outline` yields one item per `Examples` row. A `Then` unobservable locally → *Not covered* with
   the reason.
2. **The PR's manual steps** and its stated risks (a risk is a probe).
3. **The diff's user-visible surface**: copy, tooltips, routing (which dialog, which request), list / badge /
   column values, gated and disabled states, cache invalidation. Uncovered by any scenario → still an item,
   marked `extra`.

Each item is one observable: exact local URL (base path from the runbook) · action · pass condition in
what the operator can see, never a mechanism. **A UI item names the component as a user knows it, the change
(added / modified / removed / updated — what changes), the page, and where on the page.**

A visual item asks whether what is shown is what *should* be shown, quoting the screen's exact words —
never a presence check. Functional items that are product calls take the same framing.

## 2. Arrange every precondition

Fixtures (a run of the right type, a flag off, a seeded row, a second profile) are created and named by the
PM, never handed to the operator. Everything toggled is restored before the walk ends; the restore is
reported. Not arrangeable locally → item `blocked` with the reason; never dropped or swapped for an easier one.

## 3. One item, one question

Channel, decided per turn:

- **Operator present** (turn began with input not tagged `[prometheus]`) → `AskUserQuestion` in place.
  `header` = item id; options **Confirmed** · **Rejected** · **Blocked**; the free-text note rides on any.
- **Otherwise** → `"$CLAUDE_PLUGIN_ROOT/skills/dispatch/scripts/send.sh" --role seat "<item id>: <URL> ·
  <element> · <action> · <pass condition> — confirmed / rejected / blocked?"`, then end the turn; the answer
  wakes it.

Never batch items. Write each verdict to the record (§5) before the next question — an interrupted walk
resumes from the file. Order by page and fixture, not AC order.

## 4. Rejection

Capture while the state is live, before the next question: failing request + body, FE console, the backend
access-log line, the wrong rendered value. Then:

- **blocking** (feature broken, app wedged) → stop the walk and report.
- **non-blocking** → carry it, continue.

Never re-explain a rejection into a pass. A wrong pass condition is fixed and re-asked as a new item.

Each rejection → a fix brief to the item's implementor (`templates/implementor-brief.md`, its tab, via
`send.sh`): expected, seen, evidence, the scenario it breaks. The fix is re-walked, not assumed.

## 5. Record

`references/walk-record.md` → `<docs.specs><slug>/validation.md` (`registry.py field docs.specs --key
<project>`), one section per walk, appended.

- **Clean pass** → tick the PR's manual-pass line with date, env and item count (`branching` owns the
  body); story gate if this walk was it (`tracker`). Never on a partial walk.
- **Any rejection** → line stays unticked; fix runs through §4.
- A bring-up trap → the project runbook; a validating rule → here.

## Report

To the seat (`templates/pm-report.md`) or in place: counts first (`n confirmed · n rejected · n blocked`),
then rejections, then one line per item (id · kind · verdict · operator note), then what was not covered.
