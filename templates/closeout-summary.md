---
description: The validator's (later the engine's) change summary for vantage's /session-closeout after a story's top rung merges — sent as the closeout session's first message. Written to <story_dir>/closeout.md. Vantage decides note shapes, ids and landing by its own rules; this only states what happened.
---

This session delivered one story. Record it in the team planning vault with `/session-closeout`.

**Story:** [sc-#####](<story URL>) — <title>, Completed <YYYY-MM-DD>, merged as <PR links bottom-up>.

## The IDR — land as an architecture note

Land the story's Implementation Decision Record below as `vault/02-architecture/<sc-#####>-<slug>-idr.md`
(architecture-note shape, `tags: [architecture, idr]`, `repo: <owner/repo>`, `package: <path>`,
`linear: sc-#####`, `status: done`), linked from the story's mirror note and from the decision notes below.
Its own *Decisions* stay in it — they are not separate decision notes.

<the IDR, verbatim from <story_dir>/idr.md>

## Rulings — decision notes (human rulings only)

<One per ruling the operator or the product owner made for this story — from *What's decided*, stop
answers, the merge answer — each: the claim · who and when · why · what it replaces, if anything. "None."
when there were none.>

## Proposed vs applied tracker changes

Applied: story moved to Completed; acceptance criteria ticked (<n/m>); screenshots attached. Proposed: none.

## Open questions and next actions

<Anything the story left open, with its owner, or "None.">
