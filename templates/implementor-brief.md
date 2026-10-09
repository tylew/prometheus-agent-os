---
description: Lead (PM, later the engine) → implementor. One Ready story, its worktree and story folder, and the boundaries it builds within. The rule set itself is in agents/implementor.md.
unit: <workspace-label>
story: sc-#####
worktree: <absolute path>
story_dir: <absolute path — units.story_dir(sc-#####)>
ref: <branch, off a fresh origin/<default>>
---

# Story: sc-##### — <title>

## The story
<Link, and the Scenarios block verbatim. *What's decided* verbatim — UI changes are described there in
the user's words; change nothing visible beyond them.>

## Research
`<story_dir>/research/` — the planner's code, UI and knowledge findings. Start from them; verify what you
rely on.

## Stack
<Fresh stack off `<default>`, or "stacked on #<n> by operator choice" — then the bottom PR body carries
that line.>

## Non-negotiables (verbatim from `branching` + the registry entry)
<Pasted, not paraphrased: branch, worktree, title prefix, no sc-##### in the title, gt, draft PRs, never
sign, never a Claude author or co-author, minimal comments, explicit staging, owned paths, samples/
read-only, the validation set with VOLTUS=<worktree>.>

## Order
Analyse (four background subagents) → IDR (`report.sh --idr`) → wait for "IDR checked, start" → failing
scenario tests → code → validation → draft PRs with the scenario tests table and, on the bottom PR, the IDR
block → `report.sh --done`. Anything matching a Stop trigger → `report.sh --stopped`.
