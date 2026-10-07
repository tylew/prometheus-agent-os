---
name: validate
description: "Manual validation of a unit's change on local dev, and bringing local dev up for it. The project manager proves the served tree, arranges fixtures and opens a reviewer validate round; the reviewer builds the checklist (one item per Then clause of the operator's scenarios, the PR's manual steps, the diff's user-visible surface), walks every item in Chrome through subagents, captures evidence on a fail and reports to the PM; the operator answers one human-readable summary (Verified / Not as intended); the PM records the walk and turns a fail into a fix brief. Use to validate, QA, walk scenarios or sign off a PR before merge or deploy, and to bring up / start / run a project locally."
---

# validate — the browser is the instrument, the operator is the judge

The PM runs local dev and the operator question; a reviewer in a `validate-<pr#>` tab walks the checklist
in Chrome. Only an observation in the served app satisfies an item — code reading, a curl probe or a green
suite never does. Scope is **visual** (copy, labels, tooltips, badges, states, layout) **and functional**
(what an action does, persists, shows after reload, refreshes without one); label every item with its kind.

## 0. Local dev, proven — PM

- Bare "dev" is ambiguous: local dev vs the deployed env (`registry.py field deploy.envs --key <project>`).
  Ask, one sentence, options as choices. Deployed → not this skill.
- Bring-up and the served-tree proof: `references/dev-up.md`. Not up, or up on another branch → bring it up
  first. Never restart pieces mid-walk: observed items are invalidated.

## 1. Fixtures, then the round — PM

Arrange every precondition the scenarios' `Given`s need (a run of the right type, a flag off, a seeded row,
a second profile) and name each by id. Not arrangeable locally → listed in the brief as unavailable; the
reviewer marks its items `blocked`. Everything toggled is restored after the round; the restore is reported.

Then open the round: `open-tab.sh <ws> validate-<pr#> reviewer --pr <o/r#n>` (`agent-tabs`), brief from
`templates/validate-brief.md` (branch, sha, both probes, local base URL, fixtures, scenarios verbatim,
artifact path). A fresh tab per round.

## 2. The whole checklist before the first item — reviewer

Sources, earlier owns the wording on conflict:

1. **The unit's Gherkin scenarios** (from the brief). One item per `Then` / `But` clause; its `Given`s are
   setup, its `When` the action, the clause the pass condition — copied, not re-derived. A `Scenario
   Outline` yields one item per `Examples` row. A `Then` unobservable locally → *Not covered* with the reason.
2. **The PR's manual steps** and its stated risks (a risk is a probe).
3. **The diff's user-visible surface**: copy, tooltips, routing (which dialog, which request), list / badge /
   column values, gated and disabled states, cache invalidation. Uncovered by any scenario → still an item,
   marked `extra`.

Each item is one observable: exact local URL (base path from the brief) · element by its on-screen name ·
action · pass condition in what the page shows, never a mechanism. A UI item names the component as a user
knows it, the change, the page, and where on the page.

Mark each item **observe** (the browser can check it — a value, a state, a request) or **judge** (wording,
placement, a product call). A judge item is still walked; the browser captures exactly what is shown, and
the judgment is the operator's (§4).

## 3. Walk it in Chrome — reviewer

Load the claude-in-chrome tools (`claude-in-chrome` skill). One subagent (`Agent`) per page group — items
sharing a page and fixture, ordered to avoid back-and-forth; groups that mutate shared state run in
sequence, independent groups in parallel. Each subagent's brief: the URLs, the items verbatim, the fixtures
by id, "open a new tab, never reuse an existing one", "never trigger a JS alert / confirm", and the return
per item — what the page showed (exact text / state), a screenshot, the request and status where the item
depends on one, `pass` / `fail` / `blocked` against the condition as written.

Re-check every subagent's evidence against the condition before recording it. Write each item to the
artifact as it lands — an interrupted round resumes from the file.

**On a fail, capture while the state is live** (in the subagent's brief): failing request + body, FE
console, the wrong rendered value. **Blocking** (feature broken, app wedged) → stop the walk and report;
**non-blocking** → carry it, continue. A fail is never re-explained into a pass; a wrong pass condition is
said plainly and re-run as a new item.

Then write the summary (`references/walk-record.md` → *Summary*) into the artifact, post nothing to the PR,
and report one line to the PM: counts, blocking yes/no, artifact path.

## 4. Human verification — one question — PM

Read the artifact; add the backend access-log line for each failed request. Put the summary to the operator
as **one** question — options **Verified** (behavior and wording are what the user should get) · **Not as
intended** (the note names the line and how it should differ):

- **Operator present** (turn began with input not tagged `[prometheus]`) → `AskUserQuestion` in place,
  the summary in the question.
- **Otherwise** → `"$CLAUDE_PLUGIN_ROOT/skills/dispatch/scripts/send.sh" --role seat "validate <pr#>:
  <summary path> — verified / not as intended?"`, then end the turn; the answer wakes it.

A note on Verified is kept (usually the next story). Each fail and each Not-as-intended line → a fix brief
to the item's implementor (`templates/implementor-brief.md`, via `send.sh`): expected, seen, evidence, the
scenario it breaks. The fix is re-walked in a new validate round for the affected items, then re-verified.

## 5. Record — PM

`references/walk-record.md` → `<docs.specs><slug>/validation.md` (`registry.py field docs.specs --key
<project>`), one section per walk, appended, with the operator's answer.

- **Clean pass** (every item passed, summary Verified) → tick the PR's manual-pass line with date, env and
  item count (`branching` owns the body); story gate if this walk was it (`tracker`). Never on a partial walk.
- **Any fail or Not as intended** → line stays unticked; the fix runs through §4.
- A bring-up trap → the project runbook; a validating rule → here.

## Report

To the seat (`templates/pm-report.md`) or in place: counts first (`n passed · n failed · n blocked`, the
verification answer), then fails, then one line per item (id · visual/functional · observe/judge · verdict ·
operator note), then what was not covered.
