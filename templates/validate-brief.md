---
description: Project manager → reviewer. One validate round on local dev, a fresh session — walk the checklist in Chrome, report to the PM; the operator question stays with the PM.
unit: <workspace-label>
project: <registry key>
pr: <owner/repo#number>
round: <n>
branch: <branch> @ <sha>
proof: adds `<symbol>` ✓ · removes `<symbol>` ✓
base_url: <local base URL, from the project runbook>
artifact: <state_dir>/reviews/<owner>-<repo>-<pr>-validate-r<round>.md
---

# Validate: PR #<number>, round <n>

## Scenarios
<Operator scenarios for the items in this PR, verbatim.>

## Fixtures
<id · what it is · which scenario Given it serves. Unavailable locally: <what> — <why>.>

## Scope
<"full walk", or the items to re-walk after a fix, by id from the prior record.>

## Deliver
One round per `prometheus:validate` §2–§3: build the checklist, walk it in Chrome through subagents, write
the record and the summary to `artifact`, post nothing to the PR, then one `send.sh --role pm` line —
counts, blocking yes/no, artifact path — and end the turn. Denied actions and anything needing a call go
under *Needs a call* in the file.
