---
name: review
description: "One review round on one PR, run by the `reviewer`: read the true head, rate on five tiers with the boundary tests, check scenario fit, post Critical/High/Medium inline in one review whose event the counts and the approval gate decide, re-check earlier rounds' threads, honor stack order, report to the PM. Never approves on a condition, never merges, never edits."
---

# review

One round per session. The PM owns the loop: when a round is due, the story's counts comment, holds,
resolving threads, merges. The round posts inline findings + one closing event, then reports and ends.
Stance (discriminator) lives in the `reviewer` agent.

**Never:** edit, commit, push, restack, merge, ask a human, argue a disputed finding on the thread,
`gh pr comment`. A needed action outside the allow-list → `send.sh --role pm "denied: <action>, needed
for <why>"` and carry on with what is allowed.

## Inputs

- **Brief** (`templates/reviewer-brief.md`): PR, round, stack position, read-only worktree, scenarios
  verbatim, prior rounds' standing findings.
- **Registry** — `python3 "$CLAUDE_PLUGIN_ROOT/lib/registry.py" field <dotted> --key <k>`:
  `repo.slug`, `repo.default_branch`, `vcs.tool`, `review.docs`, `review.approval_gated_checks`,
  `packages` (`validate` per package).
- **PR**: `gh pr view <pr> --json body,headRefOid,baseRefName,headRefName,labels,author,mergeable,reviewDecision`;
  threads + earlier reviews: `gh api repos/<slug>/pulls/<pr>/comments --paginate`,
  `gh api repos/<slug>/pulls/<pr>/reviews --paginate`.

## Preconditions — any fails ⇒ no round; report to the PM why

- Label `NO_AUTO_REVIEW` or `HUMAN_NEEDED` absent. A failed read counts as present.
- PR body present (not empty, not an untouched template). Intent is an input, never reverse-engineered.
- **Stack order, bottom-up.** Bottom rung = base is `repo.default_branch`. Not the bottom ⇒ the rung
  below must stand approved (`gh pr view <below> --json reviewDecision` = `APPROVED`); else report
  "not reviewed — blocked on #<below>". A child's diff is against its parent branch, not the default branch.

## Read the true head

`gh pr view <pr> --json headRefOid` → `git fetch origin <sha>` → read in the brief's worktree, at that
sha (`git show <sha>:<path>`), or from `gh pr diff <pr>`. Never `origin/<branch>`: with `vcs.tool` =
graphite every restack force-pushes and the branch ref lags. Tell: cited lines don't match the head.

## The pass

1. **Semgrep first** on touched paths (`semgrep --config auto --sarif <paths>`); fold mechanical hits in,
   spend reasoning on the semantic class (concurrency, migrations, money/units, security). Absent ⇒ say so
   under *Covered*.
2. **Review docs as lenses** — each `review.docs` entry whose `applies_to` matches the diff, read at the
   head sha (`git show <sha>:<path>`). A finding it produces cites the doc's section.
3. **Trace the data flow.** Callers and consumers of every changed symbol; follow a changed value to
   where it lands (display, persistence, export, solver input); judge at the point of impact — a hunk
   alone confirms nothing. Dimensions: correctness, error handling (swallowed context, silent fallback),
   tests (discriminating — fails on the pre-change code), types/invariants, comments (truth; and the
   `branching` minimal-comments rule — narrative blocks, restated code, rationale belonging in the PR
   body), security.
4. **Scenario fit**, against the brief's scenarios:
   - a scenario this PR claims and the diff does not satisfy ⇒ **High**, inline at the closest hunk;
   - claimed by another rung, or unclear which PR delivers it ⇒ PM call, not posted;
   - behavior in the diff no scenario asks for ⇒ **Medium** phrased as a question + a PM call. The
     behavior itself is the operator's to decide, never the reviewer's.
5. **Validation** — `packages[].validate` for touched packages only, never repo-wide. Denied or not run
   ⇒ "not run" under *Covered*; never implied green.
6. **PR text** — a story key other than the delivered one in the body moves a story the PR does not
   deliver ⇒ Medium. Body claims the diff contradicts ⇒ finding at its consequence.
7. **Rate** every candidate per [references/findings.md](references/findings.md) — tiers, boundary
   tests, drops. Rating is where over-publication is fixed.

## Earlier rounds (round ≥ 2)

**Ours** = comments whose `pull_request_review_id` belongs to a review whose body opens with the
counts line (`**Review round`). Check them first, at the current head, before new review:

| thread | verdict at head | post |
|---|---|---|
| ours | fixed | reply "Verified fixed at `<sha>`." → list under *threads to resolve* for the PM |
| ours | open / cannot tell | one reply: what is still open, or what could not be verified |
| ours | author disputes | no reply; PM call with both positions |
| others' | fixed | reply "Verified at `<sha>`."; leave it |
| others' | anything else | nothing |

Reply = `POST repos/<slug>/pulls/<pr>/comments` with `body` + `in_reply_to` (see findings.md).
Then review only what moved since the last reviewed head. A head that reverses an earlier round may
implement a recorded decision — check the KB (`knowledge`) before re-raising. Third round with
Critical/High still standing ⇒ PM call: review and author are not converging.

Another reviewer's findings present ⇒ verify each as a claim (findings.md → *Verifying posted
findings*); never a blind duplicate.

## Post — one review, then read back

Mechanics, event table, approval gate, body: [references/findings.md](references/findings.md).
Order: re-read `headRefOid` → moved ⇒ re-verify every finding at the new head, or post nothing and
report → drop duplicates of open threads (re-read threads now) → POST → read back.

## Findings file + report

Write the round's write-up to the brief's artifact path, else
`$HOME/.claude/prometheus/reviews/<owner>-<repo>-<pr>-r<round>.md`:

- every finding, Low/Note included, with `path:line` and tier; what re-triage dropped and why;
- **Needs a call** — scenario gaps, unrequested behavior, disputes, non-convergence, out-of-competence
  areas, denied actions;
- **Threads to resolve** — ids verified fixed;
- *Covered* as posted; head sha reviewed.

Then one line, and end the turn:

```
"$CLAUDE_PLUGIN_ROOT/skills/dispatch/scripts/send.sh" --role pm \
  "review #<pr> r<n> @<sha7>: x critical · y high · z medium (held: a low · b note) — <EVENT> — <review html_url> — <file path>"
```

A failed round (gh error, unparseable diff, auth) is reported as failed, never as "no findings".
