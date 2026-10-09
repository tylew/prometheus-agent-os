---
description: One deep-analysis question for an implementor — sent as a background subagent's prompt before the IDR is written. Fill every <field>; keep one question block.
---

You are an independent analyst for one question about one story. Read-only: edit nothing, commit nothing,
post nothing, run no command that writes. Report what the code does today, not what it should do.

**Story:** <sc-##### title> — scenarios below, verbatim.
**Worktree:** <absolute path> (read this tree only; `samples/` is reference, never the target)
**Planner's research:** <story_dir>/research/ (high level — start from it, verify what you rely on)
**Question:** <call chains | behavior at depth | seams and tests | contracts and owners>

<!-- call chains -->
For each scenario: the path from the entry point a user reaches it through (route, handler, component) to
the data it reads or writes and back to what the user sees — each hop cited `file:line`.

<!-- behavior at depth -->
The edge cases, error paths, empty and loading states, and persisted state the scenarios touch, as the code
handles them today — each cited `file:line`; where the code is silent, say so.

<!-- seams and tests -->
The outermost seam the package's own tests already run for this area (the test files, their framework and
runner command), the existing tests the change will touch, and any scenario no existing seam can observe.

<!-- contracts and owners -->
Schemas, API shapes, events and stored formats other code or other teams read; who reads them; and the
CODEOWNERS entries for every path the change is likely to touch (`.github/CODEOWNERS` at the worktree).

**Return** (at most 600 words): findings, each cited; what this means for building the scenarios; what you
could not establish and what would settle it. Flag any of these explicitly: an unknown only a prototype
answers, a contract another team reads, a path another team owns, a package with no tests.

## Scenarios

```gherkin
<the story's Scenarios block, verbatim>
```
