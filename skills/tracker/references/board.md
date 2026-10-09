# Board hygiene — what may reach Shortcut

## The asymmetry

| Surface | Reversible | Therefore |
|---|---|---|
| description | yes — overwritten in place | correct freely; still read, so budgeted (`stories`) |
| comment | **no** — no delete via MCP; the UI keeps the trail | five cases only |
| state | yes | move at each gate (SKILL.md) |

Every board body: prose a non-engineer can read, objective voice, no code identifiers, no internal doc
names or jargon, never an agent's structured return. Read it back after posting. `<details>` changes
nothing: collapsed is still permanent, still content.

## What goes where

| Content | Home |
|---|---|
| what changes, why, scenarios, AC | description (`stories`) |
| decisions made, open questions | description — *What's decided* / *Still open* (PM) |
| mechanism, paths, test strategy, rollout, plan steps, rejected alternatives | `design.md` / `plan.md` / the PR |
| review findings, threads, accept/decline | the PR; the story gets case 5 only |
| deploy / validation status | state only |

## PM's description sections

Rebuild the full body from the live copy (pre-write guard, SKILL.md); change only these two:

- **What's decided** and **Still open** — formats in `stories` → *Story text* (their one home); here, also
  re-check the `question` label when an open item is answered.

A gap in Scenarios or AC → message the planner; never patch them.

## The five comment cases

Comment only when the PO must know or act and the description cannot carry it. **Unsure → don't.**

1. **Scope or AC moved** — what changed and why, product terms; the description is updated too (by the
   planner for Scenarios/AC); the comment is the notification.
2. **Blocked** — also `stories-add-relation` (`relationshipType: "blocked by"`) + the `blocked` label; no
   Blocked state exists.
3. **A question only the PO can answer** — product decision, priority, missing requirement.
4. **The operator explicitly asks.**
5. **A review round was posted** — one line: `Review round N: x critical · y high · z medium — <disposition> — <PR review URL>`.
   Three tiers only; no findings text. When → `review`.

`mcp__shortcut__stories-create-comment` (`storyPublicId`, `text`). Shapes for 1–3:

```
**Scope change** — <what moved, product terms>
Why: <one or two lines>
The scenarios now read: <changed scenario names and their Then>.
```
```
**Blocked** — <what blocks>
Unblocks when: <concrete condition>
```
```
**Question** — <the decision, answerable by a non-engineer>
Options: <A — consequence> · <B — consequence>
Blocking: <yes, work paused | no, proceeding on <assumption>>
```

One comment, never a thread; anything further → description or state. Never design iteration, plan
steps, a "design proposed / plan defined" notice, or a PR-comment echo. A sibling story in a comment is
prose, never a key or URL (it auto-links).

## PR ↔ story linking

Shortcut's GitHub integration parses PR **body and comments**: a bare `sc-#####`, a pasted story URL, or a
markdown link to either links that story and drives its state.

- **A PR body references exactly one story** — the one it delivers. More → sub-issues (`create.md`).
- **Sibling story: prose only** — no key, no URL, no link.
- **Unrelated PR (body or comment): `#NNNNN` only** — never a story ref on a PR that story does not deliver.

**Wrong link — repair.** Cannot be undone from here: `mcp__shortcut__stories-remove-external-link` reports
"Removed external link…" and changes nothing — it edits `external_links`; the attachment lives in the
integration-managed `pull_requests`. Editing the PR text does not unlink either.
- Verify via `stories-get-by-id` → `pull_requests`, never the success string. Still there → hand removal to
  the operator (Shortcut UI).
- Every later PR event re-advances the wrong story. Now: `stories-get-history` → the true pre-attach state
  (integration moves carry the `pull-request` entity) → restore with `stories-update` → get the link
  cleared before the PR merges.

## Readiness — the `ready_for_development` bar

Intake is lean and meets none of this by design. The bar is met in `design.md` (`knowledge`); the
description carries only its behavior part. Not ready → stays `backlog_state`, or `needs_further_scoping`
for an intake-level gap, labelled from config `labels` (`needs-scoping`, `needs-design`,
`needs-breakdown`, `question`).

| Type | Bar |
|---|---|
| all | scenarios + AC confirmed; no blocking *Still open*; recorded decisions read and followed or explicitly superseded; estimate re-checked ≤ 5 |
| feature | expected behavior; out of scope; target paths (outside `owned_paths` = cross-cutting → operator go-ahead now); work-item breakdown; test expectations + suite; rollout (any schema change called out); observability |
| bug | observed vs expected; reproduction or evidence; affected area; impact; validation environment; origin (*relates to* the shipped change, or "unknown" + why); duplicates folded |
| chore | current state + its cost; target state; scope; why now; behavior change (a "none" the test plan proves); risk + reversal |

- Gaps are fixed in `design.md`, never posted as a list. Only a PO-only question or a blocker comments.
- Ready posts nothing — the state move is the signal.
- Urgency shortens clarification, not the bar. Unknown scope → a `spike`-labelled time-boxed story whose
  output is the scope. Too big to size → split (`create.md`).
- An assumption is written into *What's decided* / *Still open*, never silent.

## Screenshots

A user-visible change's screenshots live in the description's one `<details>`, written by the validate
round's reviewer on a Verified walk (`validate` §4b): `<summary>What does it look like?</summary>`, then one
`![<what it shows>](<url>)` per image. Upload first, through Chrome on the story page: the attachment
input via `mcp__claude-in-chrome__file_upload` with the saved file's absolute path
(`mcp__shortcut__stories-upload-file` runs remotely and cannot read a local path); read each url back from
the story's `files` (`stories-get-by-id`). Chrome on Shortcut's login page → "Log in with SSO", then the
work Google account already signed in to Chrome; never type a password — no session ⇒ report it, nothing
uploaded. The story is the screenshots' only home: never the repo, never a comment.
