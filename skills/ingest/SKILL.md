---
name: ingest
description: "How any source pipeline — meeting notes, PRs, stories, operator notes — turns raw material into an ingest proposal for kb.py apply: extract mentions and facts, mark each fact's basis, never assert what the source does not state. For pipelines outside the delivery agents."
---

# ingest

For any pipeline that turns raw material — meeting notes, PRs, stories, operator notes — into knowledge. The
pipeline extracts; `kb.py` decides what is true enough to land. One source → one proposal
(`templates/kb/ingest-proposal.json`).

## Writing a proposal

- **source** — `kind`, `ref` (`granola:<id>`, `owner/repo#n`, `sc-#####`, `operator`), `date`.
- **entities** — one per thing mentioned, by the name as it appeared (`mention`) plus its `type` and `scope`.
  Add `aliases` only when the source shows them ("Reuben (RPP)").
- **facts** — one claim per fact, one line, in the source's terms:
  - `text` — a plain fact; `field` + `value` — a structured field (`role`, `team`, `handles.slack`, `kind`);
    `interaction` — what a person decided, asked for or committed to.
  - `basis` — `decided` (an explicit decision), `merged` (a merged PR / Completed story), `stated` (asserted as
    fact by someone who would know — **requires `quote`**, the exact span), `confirmed` (the operator said so),
    else `tentative`.
- **decisions** — only explicit choices among real alternatives, with `binds_to` the story it ships in.
- **edges** — `from` / `edge` / `to` between mentions or slugs.

## Never

- Assert what the source does not state, upgrade a basis, or paraphrase a quote.
- Resolve an ambiguous name yourself — submit the mention; the library holds it for the operator.
- Write `docs/kb/` directly.

Run `kb.py apply <file> --dry-run`, read the writes and holds, then apply. Report what was held and why.
