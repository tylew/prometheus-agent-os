---
description: Implementor → builder. The prompt for one builder subagent (Agent, subagent_type prometheus:builder, run_in_background true) — one rung in skeleton or build mode, or one review fix. Fill every <field>; one builder at a time per worktree.
---

**Mode:** <skeleton | build | fix>
**Story:** <sc-##### title>
**Rung:** <branch> — <what this rung carries (backend / frontend), from the IDR's Split line>
**Worktree:** <absolute path> — edit only here, only in the project's owned paths: <owned paths>.
`samples/` is reference, never the target.

**Tests to make pass** (build / fix; committed, failing — never edit them):
- <absolute path> — <test names>

**Run them:** `<the package's scenario_run with <tests> filled, or the package's own test command for those files>`
**Validation set:** <the registry validate commands for each touched package, <worktree> filled>

**Finding** (fix only): <the finding verbatim, its file:line, the test that proves the fix>

**Delivery non-negotiables:** <verbatim from the implementor's brief>

## IDR

<idr.md verbatim>

## Failure modes on this rung

<the failure-modes.md rows for this rung>
