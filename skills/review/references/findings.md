# Findings — rating, posting, the closing event

Home of the rating and posting rules. The reviewer rates and posts; the PM writes the story line and
resolves threads ([review-loop.md](review-loop.md)).

## Severity — five tiers, three posted

| tier | means | posts | decides the event |
|---|---|---|---|
| **Critical** | correctness, security, data loss, money wrong — merging ships a defect | inline | yes |
| **High** | regression risk, architecture violation, gate/contract broken, scenario unmet, test gap over a critical path | inline | yes |
| **Medium** | real behavioral gap that doesn't block alone: missing edge case, error path swallowing context, comment misdescribing load-bearing code, invariant left to convention | inline | no |
| **Low** | naming, style, minor clarity, preference | **never** — findings file only | no |
| **Note** | FYI, future, another story's | **never** | no |

Counts line: `x critical · y high · z medium`. Low/Note are counted in the findings file only.

## Boundary tests — before anything posts

*(Home.)* Over-publication and under-rating are rating failures, fixed here, not by trimming the list.

- **Name the failure**: concrete input/state → wrong output, crash, corrupted record. Unstatable ⇒ not
  Critical, High or Medium: it is Low, and Low does not post.
- **A Low naming a real behavioral gap is a Medium** (uncovered error path, comment misdescribing
  load-bearing logic, invariant the type leaves to convention). Naming/style/wording stay Low whatever lens
  raised them and whatever it called them.
- **Dissolves on inspection ⇒ dropped, not downgraded** (upstream guard, unreachable branch, caller handles
  it). Publishing it costs the author time and the next review its credibility.
- **Not verifiable from the code ⇒ a Medium phrased as a question** ("assumes `x` non-null; guaranteed by
  the caller?"), never an asserted crash.
- **Unverified premise ⇒ verify, cut to the verified part, or drop.** A specialist's or another reviewer's
  "not verified" list is a posting blocklist. A false public assertion is not un-sent by an edit.
- **Evidence counts only at the layer it exercised** — a unit probe says nothing of the route that mounts
  it; a green suite after a change is consistent with inert code. Name the layer the claim lives at.
- **A Medium that should block is a mis-rated High** — re-rate and let the event follow; never condition an
  approve on it.
- **Already an open thread** (same defect, same place, anyone's) ⇒ drop; reply on theirs if it adds evidence.
- **> ~8 inline on one PR ⇒ re-triage** against these tests; the findings file records what was dropped —
  an unstated cap reads as "that was everything".

## Mapping a tool's rating

**Consequence sets severity; a tool's confidence decides only whether it is a finding at all.**

- Toolkit **Critical / Important** → Critical / High, then the boundary tests; anything a specialist
  reports below its own 80-confidence floor → Low.
- Confidence 0–100 / criticality 1–10 scales: map by the named consequence, never by the number.
- **Invented tier ⇒ re-map, never drop**: names something to change in this diff ⇒ Medium or Low; else
  Note. The findings file records which way.
- Project-lens findings (review docs, review runbooks) map onto the same scale.

## Inline comment shape

Prose standing alone on the thread: claim + evidence. Leads with `**Critical:**` / `**High:**` /
`**Medium:**` — the tier, never the merge consequence (whether a Medium blocks is the counts line's and the
event's). No lens/tool/agent names, scores, confidence, `severity:` keys. Critical/High: defect + evidence,
no fix shape (the author owns it). Medium: "Consider X: <why>", impersonal; single-line fix ⇒ a
` ```suggestion ` block. A finding is stated only inline, never repeated in the body.

**Anchors.** `line` = head-side line that is in the diff: from `gh pr diff <pr>` hunks, `+` and context
rows count, `-` rows don't. One off-diff anchor 422s the whole review. Off-diff ⇒ the nearest commentable
line in the same file, prose naming the real line. File outside the diff ⇒ the body names it. Spans anchor
on their last line and name the range. Never send `subject_type` or `start_line`.

## The closing event — from the counts, every round

*(Home.)* Derived mechanically from the counts — never from a specialist's or the reviewer's worded
recommendation.

| counts at this head | event |
|---|---|
| any Critical/High | `REQUEST_CHANGES` — the body says what clears it |
| 0 critical · 0 high, gate holds | `APPROVE` |
| 0 critical · 0 high, a gate condition open | `COMMENT`, naming the open condition |
| unrequested review (brief `requested: no`), 0 critical · 0 high | `COMMENT` ([review-loop.md](review-loop.md) → *Unrequested review*) |
| own PR, any counts | `COMMENT`; the counts line states the event the rows above give ("changes requested" only for Critical/High; Mediums alone ⇒ "clean at this head" or the open gate condition) |

**Nothing is approved on a condition.** *(Home.)* An approve means the gate held at the head it names; a
Medium never conditions it however many stand. Rigor lives in the severity and in the loop coming back.

**Request-changes is the normal non-clean outcome**, and the loop owns clearing it: the round that drives
the counts to zero closes `APPROVE` from the same account and supersedes it. A standing approval made untrue
by new content is superseded by this round's `REQUEST_CHANGES`; the body says what changed.

**Approval gate** — every condition read this round; a failed read is a no, never a pass:

1. 0 critical · 0 high at the head.
2. Head = the sha the findings were verified at, or the same diff by patch-id (a pure restack); re-read
   immediately before posting.
3. No open thread of ours: every finding of ours from earlier rounds verified fixed at this head (the PM
   resolves them; an approve with ours open lets a repo that keeps approvals across a push merge on it).
4. `gh pr checks <pr>`: all passed, none pending — except names in `review.approval_gated_checks` (they
   wait on an approval and would deadlock the gate). Unlisted pending ⇒ open.
5. `mergeable` = `MERGEABLE` (`UNKNOWN` = still computing ⇒ open).
6. On a stack, the rung below approved; body carries **Stack order**.
7. No `HUMAN_NEEDED` label, no hold.
8. The review was requested of the operator (brief `requested: yes`).
9. A teammate's PR that delivers a story: every acceptance criterion on the story is checked (Shortcut
   `stories-get-by-id`). Ticking them is the author's; unchecked ⇒ open, and the round says which.

Scenario acceptance as a whole is not in the gate: it is `validate`'s, and the merge is the operator's.

## Body — this order, parts that hold only, never "none"

1. **Opening** — unrequested review only: one sentence, "Review not requested; posted because this change
   touches paths the reviewing team owns."
2. **Counts** — `**Review round <n>: x critical · y high · z medium.**` (own PR: append "— changes
   requested on the threads below" or "— clean at this head", then "(submitted as a comment event because
   GitHub does not accept an approval or a change request from the PR's own author)").
3. **Summary** — 2–3 sentences: what the change does, the read, themes. Never a per-finding list.
4. **To clear this review** — required on `REQUEST_CHANGES`: tiers by count ("the 1 High thread") + any
   show-stopper that is not line-level (broken migration path, missing gate, an approach that fails on real
   data), once. It is what the next round checks.
5. **Earlier rounds** — round ≥ 2: N of M prior threads verified fixed; what stands. One line.
6. **Covered** — every round: surfaces read, Semgrep, specialists run, suites run with real counts, what
   was not verified. Without it a zero line cannot be told from a pass that did nothing.
7. **Not a gate** — required on `APPROVE`: what it does not cover (other owners' paths, unrun suites, CI red
   inherited from the base). An approval implying more assurance than was obtained is worse than none.
8. **Needs another reviewer** — area outside competence + owning team, when it applies. The approve still
   stands for what was covered.
9. **Direction** — a decision the PR takes that may need to go the other way, when it applies.
10. **Stack order** — on a rung: "#N merges first".

Everything else — per-finding detail, held-back Low/Note, the long read — goes to the findings file.

**Every outward body is rendered, read and checked** — review body, inline, reply. Write it out, read it
back:

| check | fails when |
|---|---|
| non-empty prose | empty; JSON, a tool result, a findings object, frontmatter — a specialist's return is an input, never a body |
| states the finding, not the machinery | agent/lens/runbook names, scores, confidence, `severity:` keys |
| objective voice | first-person "I", praise, thanks, a name or sign-off |
| internal stays internal | spec paths, plan jargon, slugs, runbook names |
| request-changes says what clears it | `REQUEST_CHANGES` without *To clear this review* |
| approve claims only what held | `APPROVE` with non-zero Critical/High — the event is wrong, not the body |
| no sibling story ref | a story key, URL or link other than the delivered story's |

## Before posting — verified at the head it names

| check | how |
|---|---|
| head unmoved | `gh pr view <pr> --json headRefOid` = the sha the findings were verified at; moved ⇒ re-verify each at the new head and post against it, or post nothing and report |
| every finding still holds | re-read each `path:line`; a push mid-pass is often the fix |
| no duplicate of a thread opened since the brief | re-read the comments + reviews APIs now — a pass is long and another reviewer's round lands inside it; already a thread ⇒ drop it, reply on theirs if it adds evidence |
| the approve's gate holds | every condition above, read this round |
| on a stack, the rung below closed clean | [stacks.md](stacks.md) → *The bottom rung is the gate* |

## Posting

One call — inline comments inside the review, so one event. Write the payload with the Write tool under the
reviews state dir, then (the reviewer's allow-list matches `gh api repos/…` with the path first — keep
`--method` after it):

```
gh api repos/<slug>/pulls/<pr>/reviews --method POST --input <payload.json>
# {"commit_id":"<head sha>","event":"REQUEST_CHANGES","body":"<body>",
#  "comments":[{"path":"<repo-relative>","line":79,"side":"RIGHT","body":"**High:** <claim + evidence>"}]}
```

- 422 "own pull request" ⇒ nothing posted; resend the same payload as `COMMENT` with the own-PR counts line.
- Any other 422 ⇒ fix the anchor it names; never drop findings to make it pass.
- **Read back**: response `.state` + `.html_url` (the review link — never hand-built) + `.body[0:80]`
  (empty or a literal path = the body did not go); then
  `gh api repos/<slug>/pulls/<pr>/comments --paginate --jq '[.[]|select(.pull_request_review_id==<id>)]|length'`
  = comments sent. Short ⇒ re-post each missing one singly:
  `gh api repos/<slug>/pulls/<pr>/comments --method POST --input <file>` with `commit_id`, `path`, `line`,
  `side`, `body`.
- **Reply** to a thread: same endpoint, `{"body":"…","in_reply_to":<comment id>}`. Each reply leaves a
  bodyless `COMMENTED` review wrapper — GitHub, not a defect.
- **Repair only**: a review body naming the wrong sha ⇒
  `gh api repos/<slug>/pulls/<pr>/reviews/<id> --method PUT -F body=@<file>` (`-f` posts the literal path).
- Exactly one review per round, clean rounds included; never a plain `gh pr comment`, never a second event.
- A request-changes stays until a later round of the same account supersedes it — the PM schedules that
  round. Another account's stale `CHANGES_REQUESTED` is the author's to dismiss
  ([addressing-review.md](addressing-review.md) step 7).
