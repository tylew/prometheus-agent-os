---
description: Project manager → reviewer. One PR, one round, judged fresh against the unit's operator-defined scenarios.
unit: <workspace-label>
pr: <number>
round: <n>
stack_position: <n of m | standalone>
worktree: <absolute path, read-only>
---

# Review: PR #<number>, round <n>

## Scenarios the PR must satisfy
<Operator scenarios for the items in this PR, verbatim.>

## Prior rounds
<Standing findings to re-check, or "first round".>

## Deliver
Findings posted per `ship-review`; report to the PM: counts by severity, review link, and anything
that needs a PM or operator call (behavior beyond the scenarios, scenarios not met).
