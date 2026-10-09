---
name: knowledge
description: "The knowledge base at docs/kb/ and the spec tree at docs/specs/. Which note type holds what (person, org, concept, system, topic, decision), general vs project scope, the truth gate (only final, sourced facts land; the rest waits in the inbox), writing only through kb.py proposals, and the gated lifecycle triage → design → plan → implement."
---

# knowledge

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

`docs/specs/<project>/<slug>/{design,plan}.md` — the read-only contract once confirmed: never moved, renamed or
deleted. Lifecycle triage → design (operator confirms) → plan (operator confirms) → implement; no stage skipped.
The project's spec dir is `registry.py field docs.specs --key <project>`.
