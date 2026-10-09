---
name: validate
description: "The end of a story, run by one validator session per story: bring local dev up and prove the served tree, arrange fixtures, build the checklist (one item per Then clause, the PR's manual steps, the diff's user-visible surface), walk it in Chrome through subagents with screenshots, ask the operator ONE question in its own tab (Verified, merge · Verified, hold · Not as intended), tick the acceptance criteria with evidence, re-check the gate and merge the stack bottom-up, then open the vantage closeout. Also the merge of a teammate's PR when the operator explicitly asks. Use to validate, QA, walk scenarios, sign off or merge a story, and to bring up / start / run a project locally."
---

# validate — the browser is the instrument, the operator is the judge, one question ends a story

The **validator** (`validator-sc-<id>` tab, `agents/validator.md`) owns every step below. Only an
observation in the served app satisfies an item — code reading, a curl probe or a green suite never does.
Scope is **visual** (copy, labels, tooltips, badges, states, layout) **and functional** (what an action
does, persists, shows after reload); label every item with its kind.

## When a validator opens

The operator's own story, when every rung of its stack: passes our review approval gate except the approval
itself (GitHub rejects the author's own), has a teammate's approval, and has every check green except
`review.approval_gated_checks`. One validation at a time per project: the base checkout is shared and
hot-reloads, so a second story waits in the feed.

## 0. Local dev, proven

- Bring-up and the served-tree proof: `references/dev-up.md` — on the stack's **top** branch, from the base
  checkout. Not up, or up on another branch → bring it up first. Never restart pieces mid-walk: observed
  items are invalidated.

## 1. Fixtures

Arrange every precondition the scenarios' `Given`s need (a run of the right type, a flag off, a seeded row,
a second profile) and name each by id. Not arrangeable locally → its items are `blocked`, with why.
Everything toggled is restored after the walk; the restore is recorded.

## 2. The whole checklist before the first item

Sources, earlier owns the wording on conflict:

1. **The story's Gherkin scenarios.** One item per `Then` / `But` clause; its `Given`s are setup, its
   `When` the action, the clause the pass condition — copied, not re-derived. A `Scenario Outline` yields
   one item per `Examples` row. A `Then` unobservable locally → *Not covered* with the reason. The PRs'
   `manual:` scenario-test rows are items too.
2. **The PRs' manual steps** and their stated risks (a risk is a probe).
3. **The diff's user-visible surface**: copy, tooltips, routing, list / badge / column values, gated and
   disabled states, cache invalidation. Uncovered by any scenario → still an item, marked `extra`.

Each item is one observable: exact local URL · element by its on-screen name · action · pass condition in
what the page shows. Mark each **observe** (the browser can check it) or **judge** (wording, placement, a
product call — walked and captured; the judgment is the operator's).

## 3. Walk it in Chrome

Load the claude-in-chrome tools. One subagent (`Agent`) per page group — items sharing a page and fixture;
groups that mutate shared state run in sequence, independent groups in parallel. Each subagent's brief: the
URLs, the items verbatim, the fixtures by id, "open a new tab, never reuse an existing one", "never trigger
a JS alert / confirm", and the return per item — what the page showed (exact text / state), a screenshot
saved to `<artifact without .md>/<item #>.png` (copied out of the browser tool's temp dir as it lands), the
request and status where the item depends on one, `pass` / `fail` / `blocked`.

Re-check every subagent's evidence against the condition before recording it. Write each item to the
artifact as it lands. **On a fail, capture while the state is live**: failing request + body, FE console,
the wrong rendered value, the backend access-log line. **Blocking** (feature broken, app wedged) → stop the
walk; **non-blocking** → carry it. A fail is never re-explained into a pass.

Then write the summary (`references/walk-record.md` → *Summary*) into the artifact.

## 4. One question — in the validator's own tab

`AskUserQuestion`, once, the human-readable summary in it: the story; the PRs bottom-up with their
approvals and checks; counts (`n passed · n failed · n blocked`); fails and judge items; what is not
covered; anything outstanding. Choices:

- **Verified, merge** — behavior and wording are what the user should get; merge now.
- **Verified, hold** — merge later; the note names until when: a date, a named PR merging, or "until I
  say".
- **Not as intended** — the note names the line and how it should differ.

The dialog holds only this session; nothing else in the epic waits on it.

## 5. The story

- **Verified** (either form) → per `tracker` (pre-write guard, full description, re-read): tick `- [ ]` →
  `- [x]` for each criterion whose items all **passed** in this walk; a criterion with a failed, blocked or
  not-covered item stays unticked, named with why. The user-visible screenshots go into the description's
  one `<details>`. Tick each PR's manual-pass line with date, env and item count; point its *Screenshot or
  Video Demo* at the story. Never on a partial walk.
- **Not as intended**, or any fail → nothing on the story; each line becomes a fix brief to the
  implementor (`report.sh --needs-you` is not used: one line to the lead naming the artifact); the story
  goes back to implement and gets a fresh validator after the fix.

## 6. Merge — on "Verified, merge" (or a hold whose condition is met)

1. **Re-read the gate at the current heads**, every condition, a failed read is a no: each rung approved,
   checks green, mergeable, no open thread of ours, heads equal to the walked ones (or the same diff by
   patch-id). Anything moved → no merge; report; a review round is due.
2. **Bottom-up**, for each rung: `gh pr merge <n> --squash --match-head-commit <head sha>` — never
   `--admin`. Then in the stack's worktree `gt sync` (restacks the next rung onto `<default>`) and wait for
   its retarget and checks; approvals survive the push (`dismiss_stale_reviews_on_push` is off). A dismissed
   approval or a red check → `waiting: re-approval` / the check, reported, the merge resumes when it clears.
3. The story moves to Completed when the top rung merges (`tracker`; the integration usually moves it —
   re-read, move only if it did not).
4. **Partial outcomes are states**, reported and shown on the map, never silent: `merging: rung 2/3`,
   `held: <until>`, `done · closeout pending`.

## 7. Closeout — the IDR and the story's rulings into the planning vault

After the top rung merges: write `<story_dir>/closeout.md` from `templates/closeout-summary.md` (the IDR,
the story's human rulings with who and when, links), open `closeout-sc-<id>` (`open-tab.sh <ws>
closeout-sc-<id> closeout --item sc-<id> --worktree <the project's base checkout>`), send it the summary as
its first message, then `/session-closeout`. Vantage lands it by its own rules (one direct `plan(<team>):
…` commit). It may ask the operator to approve its proposals in its own tab. Not landed → the story shows
`done · closeout pending` with the tab to open.

## A teammate's PR

Never merged by prometheus unless the operator explicitly asks, naming the PR. Then a validator runs §6
only — no walk, no story ticks, no closeout — and §4 becomes one question: "merge #<n>?" with the gate.

## Record

`references/walk-record.md` → `<story_dir>/validation.md`, one section per walk, appended, with the
operator's answer. A bring-up trap → the project runbook; a validating rule → here.
