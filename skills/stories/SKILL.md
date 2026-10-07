---
name: stories
description: "The behavior-spec story standard and lifecycle: who writes stories (the planner only), the draft → operator-confirmed → created flow through docs/specs/<project>/backlog/, the five-heading body with 3–5 Gherkin scenarios and one checkbox per scenario, splitting into parent + sub-issues, and who may edit which part of a story afterwards (planner: scenarios + AC; PM: state, What's decided, Still open)."
---

# stories

Home of the story body standard. A story is a behavior spec: *what* a user sees change, never *how*.
Shortcut mechanics (create, update, link, states, comments) → `tracker`. Specs and plans → `knowledge`.

## Who

| | `planner` | `project-manager` |
|---|---|---|
| Creates stories | only author | never — scope gap → `send.sh --role planner` |
| Owns in the body | title, type, epic, estimate, *What we're building and why*, `Feature`, Scenarios, acceptance criteria | state, *What's decided*, *Still open*, ticking boxes |

A change to Scenarios or acceptance criteria — from a PM, review or design — goes back to the planner,
then the operator. Nobody else rewrites them.

## Lifecycle

1. **Source** — an operator ask, a meeting-derived candidate, a PM scope request, an existing candidate.
   Scope unknown → not a story: leave it a candidate, or a time-boxed spike whose output is the scope.
2. **Draft** — `<specs>/backlog/<slug>.md` from `templates/story.md` (parent: `templates/story-parent.md`),
   `<specs>` = `python3 "$CLAUDE_PLUGIN_ROOT/lib/registry.py" field docs.specs --key <project>`.
   Body below the frontmatter = exactly what is posted; frontmatter is local only. `status: draft`.
3. **Confirm** — the operator confirms the scenarios. The planner proposes wording, never behavior: a
   behavior the operator has not stated is a question. One sentence per fork, the drafted behavior
   named, options as choices. Confirmed → `status: confirmed`. Nothing reaches Shortcut before this.
4. **Create** — per `tracker`: Backlog, type, epic homed, owner, then estimate; read back. Write
   `story: sc-#####` + `status: created` into the draft, then delete the draft. A draft found with
   `story:` set is already created — delete it, never recreate.
5. **Report** — the new story ids to the planner's PM, which keeps them in its unit or proposes a separate
   unit to the seat.

After creation the description is the record. `design.md` carries the Scenarios block **verbatim** from
the story; it never forks its own. Any edit to the description: re-fetch, replace only your own
sections, overwrite, read back — never post from a stale copy.

## Title and type

- **Title** = verb + an outcome a user can see: "Show the plan discount on the invoice PDF", not
  "Invoice PDF: discount field, resolver, seed". No status words, never `sc-#####`.
- **Type**: `bug` = exists and misbehaves · `feature` = does not exist yet · `chore` = no user-facing
  change. Missing UI is a feature, not a bug. Classify by reality, not by how it was reported.

## The body

**Two passes.** Outline one line per claim (the gap · the change · each decision · each open item · each
scenario); then render each in the fewest words that carry it. Never compose prose into the headings.

- **Budget: 150–200 words of prose; 300 is the ceiling, not the target.** Past 300, cut — delete, don't
  collapse. The Scenarios block is outside the count, capped at 3–5 scenarios instead.
- **Five headings, exact text, this order:** `## What we're building and why` · `## What's decided` ·
  `## Still open` · `## Scenarios` · `## Acceptance criteria`. No engineering heading: paths, test
  plans, rollout, merge order → `design.md` / `plan.md` / the PR.
- **No code identifier anywhere** — no path, class, function, column, table, endpoint or flag key, in
  any section. Test: would a product user who cannot read the code recognise the name? A flag is named
  by what it gates ("while the release flag is off"). Exception: words the product shows on screen.
- **What we're building and why** — today's behavior → the gap → "This story …" saying what a user sees
  change. Business before mechanism. Bug: the symptom leads, then what should happen instead. No
  root-cause essay.
- **What's decided** — `- **the claim** (Name, YYYY-MM-DD).` A reason clause only when the claim reads
  as arbitrary without it. "Nothing yet." when none. A changed ruling says what it replaces; the
  replaced bullet is deleted.
- **Still open** — `- **Name:** the ask. Blocks this story.` or `… Not blocking: we build <default>; a
  different answer changes <what>.` One owner per item; "Nothing." when none. Answered → fold into
  *What's decided*, delete the item.
- **At most one `<details>`**, omitted by default, titled with the question a PO would ask ("who does
  this affect?"). Blank lines around its inner content. Never the only copy of anything.
- No link to a local spec or plan; internal docs and their jargon stay out.

## Scenarios

One fenced `gherkin` block, **3–5 scenarios**, behavior only.

- `Feature` + `As a / I want / So that`, then `Scenario` or `Scenario Outline` + `Examples`.
- **`Then` = what a user can observe.** "Then the invoice PDF shows a Plan discount line" is a scenario;
  "Then the row is written to the discount column" is a plan step.
- One `When` — the single user action.
- Same behavior across inputs → one `Scenario Outline`, not one Scenario per input.
- `Background` only when **every** scenario needs the same `Given`.
- Cover the no-change case (legacy record, other party, the negative). A story shipping behind a flag
  owes a flag-off scenario.
- Each scenario name stands alone — it becomes a checkbox and a validation item.
- **More than 5 → the story is too big: split.**

## Acceptance criteria

One `- [ ]` per scenario, in block order, the name **verbatim**. No criterion that is not a scenario, no
scenario without a box; a `Scenario Outline` is one box. An internal-structure assertion ("no second code
path", "a test fails if the check is removed") is a plan step → `plan.md` / the PR. Boxes are ticked as
validation confirms each scenario.

## Estimate and split

Fibonacci **1 · 2 · 3 · 5 · 8**; target ≤ 5. Size on implementation surface, design reach (new pattern,
shared code), validation effort, and dependencies. Re-checked when `design.md` settles scope; a re-check
landing on 8 splits.

**Split** when scenarios exceed 5 or the estimate is 8: a parent from `templates/story-parent.md` plus
one sub-issue per slice, each a full story from `templates/story.md` with its own 3–5 scenarios and
estimate ≤ 5. The parent carries no Scenarios block; its acceptance criteria are its sub-issue titles,
done when each is Completed. The operator confirms the split with the scenarios. Each child is created
and homed like any story, then linked to the parent (`tracker`). One design for the package, at the
parent's spec folder; one plan per child.

Worked example of the register and scenario grain: `references/example.md`.
