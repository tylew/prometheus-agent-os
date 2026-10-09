---
description: How the story's change can fail, written by the implementor with the IDR at <story_dir>/failure-modes.md from the behavior-at-depth and call-chain analyses. Each mode gets a test (named exactly as the test runner reports it) or "cannot happen: <why, cited>". Read by the IDR check; every named test is checked by lib/proof.py. Delete this frontmatter.
---

| Mode | Where today | Test | Rung |
|---|---|---|---|
| <the input or state, and what goes wrong> | <file:line> | <test name> | <backend / frontend> |
| <…> | <file:line> | cannot happen: <why, cited file:line> | — |

<!-- Look through, not a quota: empty and missing data, nulls, sign, units and scale, time zones and DST,
     ordering and duplicates, old records and frozen versions, permissions, concurrent edits, the flag off.
     A mode the analyses show and this table omits is an IDR-check finding. -->
