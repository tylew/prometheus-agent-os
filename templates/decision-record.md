---
description: Project manager → librarian. One decision, handed off when made; it waits in the KB inbox until binds_to settles (every bound story Completed → recorded; any Won't Fix → dropped; `basis: confirmed` settles `operator` at once).
unit: <workspace-label>
project: <registry key>
spec_dir: <docs/specs/<project>/<slug>/>
binds_to: [<sc-##### | operator>]
basis: <decided | confirmed — the operator answered in your tab>
signoff: <confirmed spec path | meeting id | operator (<tab>, <date>)>
date: <YYYY-MM-DD>
---

# <Decision, as a statement>

## Context
<The question it settles.>

## Decision
<What was decided — as given, not reinterpreted.>

## Evidence
<Paths, PRs, measurements. basis confirmed: the question asked and the operator's answer, verbatim.>

## Supersedes
<Earlier decision or note, or "none".>
