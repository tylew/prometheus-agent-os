---
description: Lead (PM, later the engine) → validator. The end of one story — local dev, the walk, the one question, the merge, the closeout — per prometheus:validate.
unit: <workspace-label>
project: <registry key>
story: sc-##### — <title>
story_dir: <absolute path — units.story_dir(sc-#####)>
stack: <owner/repo#n bottom> → … → <owner/repo#n top>
heads: <#n @ sha, one per rung — what the review gate and the approvals cover>
worktree: <the stack's worktree, absolute — for gt sync during the merge>
base_url: <local base URL, from the project runbook>
artifact: <story_dir>/validation-r<n>.md
teammate_merge: <no | yes — the operator asked by name: "<their words>">
---

# Validate and merge: sc-#####

## Scenarios
<The story's Scenarios block, verbatim.>

## Gate at hand-off
<Per rung: our review gate (counts, clean at head), the teammate approval (who), checks. Anything not yet
green is named — re-read it yourself before the walk and before each merge.>

## Fixtures known
<id · what it is · which Given it serves, or "arrange per §1".>

## Scope
<"full walk", or the items to re-walk after a fix, by id from the prior record.>
