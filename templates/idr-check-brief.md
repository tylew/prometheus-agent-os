---
description: Lead (PM, later the engine) → reviewer. The IDR check before any code — a fresh reviewer session (review-idr-sc-<id>), read-only, never asks. Its findings go to the implementor; a behavior finding to the story's planner.
unit: <workspace-label>
project: <registry key>
story: sc-##### — <title>
idr: <story_dir>/idr.md
ref: origin/<default branch> (fetch first; read nothing else as current code)
round: <1 | 2>
artifact: <story_dir>/idr-check-r<round>.md
---

# IDR check: sc-#####

Read the story, then the IDR. Check, citing the IDR line and the evidence for each finding:

- **Coverage** — every scenario has its place in *Approach* and a seam in *Where the scenarios are tested*.
- **Consistency** — nothing contradicts the story's *What's decided* or an active decision the story cites.
- **Grounding** — *Approach* claims about today's code hold when spot-checked at `ref` (call chains,
  contracts, the named seam's existence).
- **Form** — `python3 "$CLAUDE_PLUGIN_ROOT/lib/idr.py" check <idr>` is clean.

Rate with the review tiers (`prometheus:review` → findings). Write the findings to `artifact`, post nothing,
and send the lead one line: counts, `clean` or not, behavior findings named, the artifact path.

## Scenarios
<The story's Scenarios block, verbatim.>

## What's decided
<Verbatim.>
