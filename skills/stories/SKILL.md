---
name: stories
description: "The story standard and lifecycle: who writes stories (the planner only), research → draft → operator-confirmed → created → Ready, the BDD-voice body (vantage story style) with one Gherkin block and one checkbox per scenario, the definition of ready and its readiness comment, splitting into parent + sub-issues, and who may edit which part afterwards."
---

# stories

Home of the story body standard in prometheus. A story is a behavior spec: *what* a user sees change,
never *how* — the how is the story's IDR. Canonical sources, which this file applies and never forks:
vantage `rules/story-style.md` (BDD voice) and voltus-kanban `rules/definition-of-ready.md` (BDD column),
in `voltusdev/voltus-custom-skills-hub`. Shortcut mechanics → `tracker`.

## Who

| | `planner` | engine / PM | `validator` |
|---|---|---|---|
| Creates stories | only author | never — scope gap → the planner | never |
| Owns in the body | everything: title, type, epic, estimate, all five sections | state, labels | ticking acceptance boxes with evidence |

A change to Scenarios or acceptance criteria — from review, a stop or the IDR check — goes back to the
story's planner, then the operator. Nobody else rewrites them.

## Lifecycle

1. **Source** — an operator ask, a discovery planner's preliminary issue, a meeting-derived candidate, a
   scope gap. Scope unknown → a spike whose output is the scope, not a story.
2. **Research** — the planner's three lenses (`agents/planner.md`); findings saved with the story.
3. **Draft** — `<specs>/backlog/<slug>.md` from `templates/story.md` (parent: `templates/story-parent.md`),
   `<specs>` = `python3 <plugin>/lib/registry.py field docs.specs --key <project>`. Body below
   the frontmatter = exactly what is posted. `status: draft`.
4. **Confirm** — the operator confirms the scenarios, each UI change and the flag decision, in the
   planner's tab. A behavior the operator has not stated is a question. → `status: confirmed`.
5. **Create or overwrite** — per `tracker`: a new story in Backlog (type, epic homed, owner, then
   estimate); an existing story's description overwritten. Read back. Write `story: sc-#####` +
   `status: created` into the draft, then delete the draft; a draft with `story:` set is never recreated.
6. **Ready** — the definition of ready (below); one readiness comment; Ready for Development when every
   criterion holds.

After creation the description is the record. The IDR never restates the scenarios. Any edit: re-fetch,
change only what you own, overwrite, read back — never post from a stale copy.

## Title and type

- **Title** = verb + an outcome a user can see: "Show the plan discount on the invoice PDF". No status
  words, never `sc-#####`.
- **Type**: `bug` = exists and misbehaves · `feature` = does not exist yet · `chore` = no user-facing
  change. Missing UI is a feature, not a bug.

## The body — BDD voice

**Two passes.** Outline one line per claim; then render each in the fewest words that carry it.

- **Budget: 150–200 words of prose; 300 is the ceiling.** The Scenarios block is outside the count.
- **Sections, exact headings, this order:** `## What we're building and why` · [`## What we saw
  (YYYY-MM-DD)`, bugs and review findings only] · `## What's decided` · `## Still open` · `## Scenarios` ·
  `## Acceptance criteria`. No `## Engineering notes`: paths, seams, test plan, rollout → the IDR.
- **No code identifier and no file named, anywhere** — no path, class, function, column, table,
  endpoint. **One exception:** the release-flag sentence in *What's decided* carries the flag key in
  backticks ("Ships dark behind the release flag `invoices-release-pdf`; with the flag off nothing
  changes."). Inside the Scenarios block the flag is named in words. Words the product shows on screen
  are not identifiers.
- **What we're building and why** — today's behavior → the gap → "This story …" saying what a user sees
  change; where the work came from as a named link; "Not in this story: …" for the boundary.
- **What we saw (YYYY-MM-DD)** — what was observed and where, screen text quoted exactly, screenshots,
  then **Steps to reproduce**.
- **What's decided** — `- **the claim** (Name, YYYY-MM-DD). Why.` Product decisions only. Each UI change
  in the user's words: the page, the area, the control or text as a user sees it, what changes — never a
  component name. A changed ruling says what it replaces. "Nothing yet." when none.
- **Still open** — `- **Name:** the ask. Blocks this story.` or `… Not blocking: we build <default>; a
  different answer changes <what>.` "Nothing." when none.
- **At most one `<details>`**, titled with the question a PO would ask. Never the only copy of anything.
- No link to a local spec, plan or vault note; internal jargon stays out.

## Scenarios

One fenced `gherkin` block, **3–8 scenarios** (a bug may have 2), behavior only.

- `Feature` + `As a / I want / So that`, then `Scenario` or `Scenario Outline` + `Examples`; optional
  `Background` (only a `Given` every scenario shares) and `Rule`.
- **One behavior per scenario; the name states the outcome** ("Monthly plan shows no discount line").
- **Declarative, in the reader's words** — never a click path, selector, endpoint or identifier.
- **`Then` = what a user or a test can observe.**
- One `When`; a scenario needing a second `When` is two scenarios.
- Cover the no-change case. Work behind a flag has a flag-off scenario. A bug has the failing case and a
  guard scenario.
- Each scenario stands alone; names are unique.
- **More than 8 → split.**

## Acceptance criteria

One `- [ ]` per scenario, in block order, the name **verbatim**; an Outline is one box. No criterion that
is not a scenario. Boxes are ticked by the validator, with evidence, as it proves each scenario.

## Ready — the definition of ready (BDD column)

The planner checks every item before moving the story:

- [ ] **Problem statement** — the gap, in *What we're building and why*.
- [ ] **Expected behavior** — what the system does after the change.
- [ ] **Out of scope** — "Not in this story: …".
- [ ] **Scenarios** — the block parses, pairs one-to-one with its checkboxes, every `Then` is observable;
      no how anywhere (no engineering section, no file named).
- [ ] **Flag decision** — the flag sentence in *What's decided* (key, context kind, default = old
      behavior), or why no flag; an epic's release flag named instead when the epic has one.
- [ ] **Dependencies** — no open *blocked by*; a story that gains one returns to Backlog until it resolves.
- [ ] **Planning links** — as Shortcut doc or story URLs, never a vault note.
- [ ] **Estimate** — Fibonacci, ≤ 5 targeted, 8 splits.

Target package, test seam, rollout and observability are not asked of the story: the IDR holds them.

**One readiness comment** (it replaces the board's five-case comment rule for this one purpose):

```
**Readiness review sc-#####:** ready — <one line: scope and what makes it testable>.
```

or, when anything is missing (the story stays in Backlog):

```
**Not ready: sc-#####** — missing: 1. <criterion> (<who owes it>) 2. …
```

Signed per `tracker`. All met → move the story to **Ready for Development** (`tracker`), read back.

## Estimate and split

Fibonacci **1 · 2 · 3 · 5 · 8**; target ≤ 5. Size on implementation surface, design reach, validation
effort and dependencies. An IDR that changes the scope re-checks it; 8 splits.

**Split** when scenarios exceed 8 or the estimate is 8: a parent from `templates/story-parent.md` plus one
sub-issue per slice, each a full story with its own scenarios, estimate ≤ 5 and its own IDR. The parent
carries no Scenarios block; its acceptance criteria are its sub-issue titles. The operator confirms the
split with the scenarios.

Worked example of the register and scenario grain: `references/example.md`.
