---
name: review
description: "PR review, both sides. The reviewer runs ONE round per fresh session: true head, Semgrep first, review docs and review runbooks as lenses, data-flow tracing, pr-review-toolkit specialists via Agent, five tiers with the boundary tests, scenario fit; posts Critical/High/Medium inline in one review whose event the counts and the approval gate decide; reports to the PM. The PM owns the loop: stack order, round-due test, holds, the story counts line, resolving threads, re-requests, closing the unit. Also the author side on the operator's own PRs (triage, reply + resolve, self-review). Never approves on a condition, never merges."
---

# review

**A review is a loop, not a pass.** *(Home.)* A PR is held round after round until it **merges, closes, or
goes on a hold** — nothing else ends it, an approve least of all ([references/review-loop.md](references/review-loop.md) → *Ending*).

| who | owns | read |
|---|---|---|
| **reviewer** — tab `review-<pr>`, `dontAsk`, a fresh session per round | one round: read, rate, post, findings file, report | this file → [review-pass](references/review-pass.md), [findings](references/findings.md) |
| **project-manager** | the loop: stack order, round due?, briefs, story counts line, resolving threads, holds, re-requests, closing the unit | [review-loop](references/review-loop.md), [stacks](references/stacks.md) |
| **PM + implementor**, the operator's own PR | review received: triage, fix, reply + resolve, re-request; self-review first | [addressing-review](references/addressing-review.md), [triage](references/triage.md), [self-review](references/self-review.md) |

No agent polls, arms a `Monitor`, runs `/loop` or background-waits: dispatcher event lines wake the PM
(`events`); the PM ends its turn whenever it waits.

## Mode triage — first, every time

Stack first: rung test both directions ([references/stacks.md](references/stacks.md)); triage against the
lowest rung not closed clean. Then:

- **No substantive review of ours yet** → round 1 ([references/review-pass.md](references/review-pass.md)).
- **Operator authored it, unaddressed review stands** (unresolved threads, findings newer than the last
  fix/reply) → [references/addressing-review.md](references/addressing-review.md). An approval does not clear
  standing Critical/High threads.
- **A round of ours exists** → a follow-up round, only when one is due ([references/review-loop.md](references/review-loop.md) → *Is a round due?*).
- **Someone else's substantive review exists, a fresh pass is wanted** → verification mode: every posted
  finding triaged as a claim ([references/triage.md](references/triage.md)) plus an independent sweep;
  never a blind duplicate.

Newest round decides: round N resolved + round N+1 untouched ⇒ the author side is pending.

## The round — reviewer

**Never:** edit, commit, push, restack, merge, ask a human, argue a disputed finding on the thread,
`gh pr comment`, resolve a thread, write the tracker. A needed action outside the allow-list →
`send.sh --role pm "denied: <action>, needed for <why>"` and carry on with what is allowed.

### Inputs

- **Brief** (`templates/reviewer-brief.md`): PR, round, `requested`, `deep`, stack (bottom-up) and
  position, read-only worktree, open threads, scenarios verbatim, prior rounds' findings files.
- **Registry** — `python3 <plugin>/lib/registry.py field <dotted> --key <k>`: `repo.slug`,
  `repo.default_branch`, `vcs.tool`, `owned_paths`, `review.docs`, `review.approval_gated_checks`,
  `packages` (`validate` per package), `runbooks`.
- **PR**: `gh pr view <pr> --json body,headRefOid,baseRefName,headRefName,labels,author,mergeable,reviewDecision,reviewRequests` — the only PR-object read (`gh api …/pulls/<pr>` is not allowed);
  threads + earlier reviews: `gh api repos/<slug>/pulls/<pr>/comments --paginate`,
  `gh api repos/<slug>/pulls/<pr>/reviews --paginate`.

### Preconditions — any fails ⇒ no round; report to the PM why

- Label `NO_AUTO_REVIEW` or `HUMAN_NEEDED` absent. A failed read counts as present.
- PR body present (not empty, not an untouched template). Intent is an input, never reverse-engineered.
- **Stack order, bottom-up.** Not the bottom rung ⇒ the rung below stands approved
  (`gh pr view <below> --json reviewDecision` = `APPROVED`; own-PR stacks: its last round "clean at this
  head"); else report "not reviewed — blocked on #<below>". A child's diff is against its parent branch.
- **Not already posted.** A review at this head whose body opens `**Review round <n>` exists ⇒ adopt it
  into the findings file; post nothing.

### Read the true head

One call each, no `cd`: `gh pr view <pr> --json headRefOid` → `git -C <worktree> fetch origin <sha>` → read
at that sha (`git -C <worktree> show <sha>:<path>`), or `gh pr diff <pr> --repo <slug>`. Never `origin/<branch>`: with `vcs.tool` =
graphite every restack force-pushes and the branch ref lags. Tell: cited lines don't match the head.
Commit ancestry and recorded decisions: [references/stacks.md](references/stacks.md) → *Reading the code*.

### The pass

[references/review-pass.md](references/review-pass.md): Semgrep → lenses → data flow → specialists →
scenario fit → validation → PR text → rate ([references/findings.md](references/findings.md)). Deep mode
only when the brief says `deep: true` ([references/deep-review.md](references/deep-review.md)).

### Earlier rounds (round ≥ 2)

**Ours** = comments whose `pull_request_review_id` belongs to a review whose body opens with the counts
line (`**Review round`); the prior findings files list their ids. Check them first, at the current head,
before new review:

| thread | verdict at head | post |
|---|---|---|
| ours | fixed | reply "Verified fixed at `<sha>`." → list under *Threads to resolve* for the PM |
| ours | open / cannot tell | one reply per head: what is still open, or what could not be verified |
| ours | author disputes | no reply; PM call with both positions |
| others' | fixed | reply "Verified at `<sha>`."; leave it open |
| others' | anything else | nothing |

Reply = `POST repos/<slug>/pulls/<pr>/comments` with `body` + `in_reply_to` ([references/findings.md](references/findings.md) → *Posting*).
Then review only what moved since the last reviewed head (restacked ⇒ the PR's diff now against its diff
then). A head that reverses an earlier round may implement a recorded decision — check `docs/kb/`
(`knowledge`) before re-raising.

### Post — one review, then read back

Mechanics, event table, approval gate, body: [references/findings.md](references/findings.md). Order:
write the findings file (status `posting`) → re-read `headRefOid` → moved ⇒ re-verify every finding at the
new head, or post nothing and report → re-read threads, drop duplicates → POST → read back → record the
review id in the findings file.

### Findings file + report

Write with the Write tool to the brief's `artifact`, else
`<state_dir>/reviews/<owner>-<repo>-<pr>-r<round>.md`:

- head sha reviewed; status (`posting` → `posted` / `not posted: <why>`); review id + `html_url`; the
  inline comment ids it opened (these define "ours" next round);
- every finding, Low/Note included, with `path:line` and tier; what re-triage dropped and why; specialist
  and Semgrep candidates dropped as unverified (count + one line each);
- **Needs a call** — scenario gaps, unrequested behavior, disputes, non-convergence, out-of-competence
  areas, a hold cause, denied actions;
- **Threads to resolve** — ids of ours verified fixed;
- *Covered* as posted.

Then one line, and end the turn:

```
send.sh --role pm "review #<pr> r<n> @<sha7>: x critical · y high · z medium (held: a low · b note) — <EVENT> — <review html_url> — <file path>"
```

A failed round (gh error, unparseable diff, auth, a specialist or Workflow that errored) is reported as
failed, never as "no findings", and never approves.

## Always applies

- **Reply + resolve each thread the moment it is dispositioned — never batched.** *(Home.)* Reviewer
  replies; the PM resolves (only threads this loop opened — [references/review-loop.md](references/review-loop.md)).
  Author side: [references/addressing-review.md](references/addressing-review.md) step 5.
- **The counts decide each round's event**; nothing is approved on a condition ([references/findings.md](references/findings.md)).
- **Critical, High, Medium post inline; Low and Note never do** — findings file only.
- **Validation is scoped to touched packages**, never repo-wide (`packages[].validate`).
- **Review content stays on the PR.** The story gets one counts line per round (PM, `tracker` → board case
  5) and reflects the rest through its state. Scope/AC moved → the planner (`stories`).
- **Internal stays internal** — specs, plans, slugs, runbooks, design jargon never reach PR text, replies,
  commits or story text; describe the mechanism. Review is where this breaks most.
- **Design-affecting feedback → PM / operator before any code** ([references/addressing-review.md](references/addressing-review.md) step 3). Unsure ⇒ design-affecting.
- **Verify before you assert** — "merged", "passing", "fixed" are self-reports until read; cite the handle.
- **Approving is not merging.** The merge is the operator's; no reviewer or PM merges unbidden.
- Outward voice: objective, impersonal — no "I", no praise, no thanks, no tics.

## References

| need | file |
|---|---|
| the pass: lenses, specialists, scenario fit, verification mode | [references/review-pass.md](references/review-pass.md) |
| tiers, boundary tests, body, event, approval gate, posting, read-back | [references/findings.md](references/findings.md) |
| the loop (PM): round due, holds, unrequested etiquette, re-requests, ending | [references/review-loop.md](references/review-loop.md) |
| stacks: rung test, walk, bottom-rung gate, true head, review worktree | [references/stacks.md](references/stacks.md) |
| a finding as a claim: verify, re-rate, dispose, fix shape | [references/triage.md](references/triage.md) |
| deep mode (Workflow, opt-in) | [references/deep-review.md](references/deep-review.md) |
| review received on the operator's own PR | [references/addressing-review.md](references/addressing-review.md) |
| self-review before requesting a human | [references/self-review.md](references/self-review.md) |
