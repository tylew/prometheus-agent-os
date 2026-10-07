---
description: Project manager → implementor. One work item, the scenario it serves, and the boundaries it builds within.
unit: <workspace-label>
item: <item-slug>
story: sc-#####
worktree: <absolute path>
ref: <branch or sha>
---

# Work item: <item-slug>

## Serves scenario
<The operator scenario this item satisfies, verbatim.>

## Build
<Scope and boundary of the item. Nothing beyond it.>

## Confirmed UI changes
<Each confirmed `ui-change` card, or "none". Change nothing visible beyond these.>

## Non-negotiables (verbatim from `branching` + the registry entry)
<Pasted, not paraphrased.>

- Write only under `<worktree>`; never the project's main checkout; `samples/` is read-only.
- Stacked on another item: when the PM says "restack", commit what you have, run `gt restack`, re-run
  validation, and report.

## Done when
<Tests that prove the scenario pass; commits on the branch; draft PR open.> Report: paths changed,
validation run and result, PR link, open questions.
