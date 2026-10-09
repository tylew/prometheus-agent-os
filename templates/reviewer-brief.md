---
description: Project manager → reviewer. One PR, one round, a fresh session, judged against the unit's operator-defined scenarios.
unit: <workspace-label>
project: <registry key>
pr: <owner/repo#number>
round: <n>
requested: <yes | no — no = a teammate's PR touching owned paths; COMMENT unless Critical/High, never approve>
deep: <false | true — true only when the operator opted in for this PR>
stack: [<#bottom>, …, <#top> | standalone]
stack_position: <n of m | standalone>
below: <#n approved | none>
worktree: <absolute path, read-only, detached at the head>
artifact: <state_dir>/reviews/<owner>-<repo>-<pr>-r<round>.md
proof: <story_dir>/proof.json | none — the build proof (the operator's stories)
failure_modes: <story_dir>/failure-modes.md | none
---

# Review: PR #<number>, round <n>

## Scenarios the PR must satisfy
<Operator scenarios for the items in this PR, verbatim.>

## Story scope
<The delivered story's scope as the board states it, quoted. Empty for a teammate's PR without one.>

## Open threads
<Unresolved review threads at brief time: comment id, path:line, author — from the PM's reviewThreads read.
Any comment newer than this brief is also open.>

## Prior rounds
<Findings files of earlier rounds (paths), the head each reviewed, or "first round".>

## Deliver
One round per `prometheus:review`: post it, write the findings file at `artifact`, then one
`send.sh --role pm` line — counts, held-back counts, event, review link, file path — and end the turn.
Anything needing a PM or operator call (behavior beyond the scenarios, scenarios not met, disputes,
non-convergence, a hold cause, denied actions) goes under *Needs a call* in the file.
