---
name: knowledge
description: "Where the record lives — the team planning vault (vantage: product rulings, architecture, delivery, story mirrors, DEC decisions, meetings, team memory), the story folder, the KB, specs, app docs — and the knowledge base at docs/kb/ and the spec tree at docs/specs/. Which note type holds what (person, org, concept, system, topic, decision), general vs project scope, the truth gate (only final, sourced facts land; the rest waits in the inbox), writing only through kb.py proposals, and the gated lifecycle triage → design → plan → implement."
---

# knowledge

## Where the record lives

| Record | Where | Written by | Read with |
|---|---|---|---|
| **Team planning vault** (vantage) — the team's shared record | `<planning.repo>` → `<planning.team_dir>/` (registry `planning`; besstie: `voltusdev/voltus-vantage-planning`, `teams/b-team/`) | vantage sessions only — for us, `/session-closeout` in the `closeout-sc-<id>` tab at Completed. Prometheus agents never write it | `gh api repos/<repo>/contents/<team_dir>/<path> --jq .content \| base64 -d`; tree: `gh api "repos/<repo>/git/trees/main?recursive=1"` |
| · `vault/01-product/` | product rulings, PRDs, program facts, open product questions | product owner | |
| · `vault/02-architecture/` | architecture notes, runbooks, debt, landed IDRs (`<sc>-<slug>-idr.md`) | chief architect | |
| · `vault/03-delivery/` | decomposition, grooming, PO reports | scrum master | |
| · `vault/04-linear/sc-<id>-<slug>.md` | story mirrors: per-story build knowledge | | |
| · `vault/05-decisions/DEC-NNNN-<slug>.md` | decision notes (ids allocated live; index `vault/_indexes/decisions.md`) | | |
| · `vault/07-meetings/`, `06-research/` | meeting and research notes | | |
| · `memory/` | team memory: `decision-log`, `product-beliefs`, `architecture-beliefs`, `tooling-beliefs`, `dependency-map`, `backlog-index`, `session-log` | | |
| **Story folder** | `<state>/engine/stories/sc-<id>/` (`units.py story-dir`): `research/`, `idr.md`, `failure-modes.md`, `proof.json`, `stop-<n>.md`, `scope-<n>.md`, `done.md`, `closeout.md` | planner, implementor, validator | files |
| **The IDR** while built | the story folder, and collapsed on the stack's bottom PR (`lib/idr.py block`); landed at Completed in `02-architecture` | implementor; closeout lands it | |
| **The story** (the what) | Shortcut | planner | `tracker` |
| **KB** | `docs/kb/` | librarian, through `kb.sh` (below) | `kb.sh search` |
| **Specs** | `docs/specs/<project>/<slug>/` — workspace and plugin work, and stories started before 2026-10-08 | per *Specs* below | files |
| **App docs** | in the product repo, e.g. `docs/code-docs/` | the story that changes them | `origin/<default>` |
| **Vantage itself** | `samples/voltus-custom-skills-hub/vantage/` (read-only); closeout runs it from `<state>/vantage-plugin` | — | files |

Before deciding in an area, read what the team already holds there: its `05-decisions` notes and
`memory/decision-log`, `01-product` rulings and `product-beliefs`, the stories' `04-linear` mirrors. An
active decision binds like *What's decided*; a conflict with it is a question for the planner, not a
silent override. Nothing here is cited in PR, commit or story text (workspace rule).

The KB (`docs/kb/`) holds only what is **true and sourced**. Specs and plans (`docs/specs/<project>/<slug>/`)
hold the gated lifecycle. Write the KB only through `kb.sh` (on every agent's PATH; wraps `lib/kb.py`); never edit `docs/kb/` by hand. `kb.sh proposal-path <name>` prints where to Write a proposal.

## Which type

| It is… | Type | Scope |
|---|---|---|
| a human | `person` (`person/<slug>/<slug>.md` overview + `<slug>-interactions.md`) | `general` |
| a team, company, customer, utility, vendor | `org` | `general` |
| a term or idea the work keeps using | `concept` | `general` or project keys |
| a service, component, pipeline, tool | `system` | project keys |
| durable how/why not about one entity | `topic` | `general` or project keys |
| a final, sign-off-backed fork | `decision` | project keys — through the inbox unless operator-confirmed |

Scope is frontmatter, never a folder. Widening scope edits the list; the note does not move.

## The truth gate

A fact lands only with a final basis — `decided` · `merged` · `stated` (with a `quote`) · `confirmed`. Everything
else is held in `<state_dir>/kb-inbox/`: tentative facts, unquoted `stated`, ambiguous mentions, a new
person or org, a field whose existing value differs, an unsettled decision. Held is not lost: `kb.py inbox` lists it,
the operator confirms (`confirm <id> [--as <slug>]`) or drops it, and a later final source releases a held fact.

**Decisions** bind to stories (`binds_to: [sc-…]`, or `operator` when no story exists). The dispatcher runs
`kb.py inbox settle --story <id> --state <state>` on Completed / Won't Fix: all bound stories Completed → the
decision is written; any Won't Fix → dropped. `basis: confirmed` with the operator's answer in `quote` settles
the `operator` binding at apply — no second ask; `confirmed` without a quote is held. A decision's `evidence` edges point at what it rests on; a
spec's `grounded_by` points at the decisions it rests on.

## Commands

```
kb.sh resolve "<mention>" [--type T]         one slug, or the candidates (exit 1)
kb.sh search  [--type] [--scope] [--text] [--edge] [--links-to <slug>] [--orphans]
kb.sh apply <proposal-path file> --dry-run   always first; then without --dry-run (never inline JSON: denied)
kb.sh inbox [list | confirm <id> [--as <slug>] | drop <id>]
kb.py check                                  schema, dangling edges, name collisions, facts without refs
```

## Specs

Stories started on or after 2026-10-08 have no spec dir: the Ready story is the what, its IDR the how.

`docs/specs/<project>/<slug>/{design,plan}.md` — the read-only contract once confirmed: never moved, renamed or
deleted. Lifecycle triage → design (operator confirms) → plan (operator confirms) → implement; no stage skipped.
The project's spec dir is `registry.py field docs.specs --key <project>`.
