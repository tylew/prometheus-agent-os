---
description: Orchestrator → project manager. The unit's scope and the operator's behavior, verbatim; the PM's only source of what to build.
unit: <workspace-label>
kind: story | story-set | goal-set | review
project: <registry key>
stories: [sc-#####]
prs: [<owner/repo#n>]
---

# Unit: <workspace-label>

## Scope
<What the operator assigned, in their words. Stories outside `stories` are out of scope.>

## Operator-defined behavior
<Gherkin scenarios / acceptance criteria, verbatim. Nothing paraphrased, nothing added.>

## Constraints
<Deadlines, dependencies, things the operator ruled out. Empty if none.>

## Report to
The seat, at each gate crossing or blocker — `templates/pm-report.md`. Keep this workspace's `stage`,
`stories` and `prs` tokens current; every PR you open joins `prs` at once.
