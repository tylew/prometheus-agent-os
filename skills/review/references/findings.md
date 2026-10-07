# Findings — rating, posting, the closing event

## Severity — five tiers, three posted

| tier | means | posts | blocks |
|---|---|---|---|
| **Critical** | correctness, security, data loss, money wrong — merging ships a defect | inline | yes |
| **High** | regression risk, architecture violation, gate/contract broken, scenario unmet, test gap over a critical path | inline | yes |
| **Medium** | real behavioral gap that doesn't block alone: missing edge case, error path swallowing context, comment misdescribing load-bearing code, invariant left to convention | inline | no |
| **Low** | naming, style, minor clarity, preference | **never** — findings file only | no |
| **Note** | FYI, future, another story's | **never** | no |

Counts line: `x critical · y high · z medium`. Low/Note are counted in the findings file only.

## Boundary tests — before anything posts

- **Name the failure**: concrete input/state → wrong output, crash, corrupted record. Unstatable ⇒ Low.
- **A Low naming a real behavioral gap is a Medium.** Naming/style stay Low whatever raised them.
- **Dissolves on inspection ⇒ dropped, not downgraded** (upstream guard, unreachable branch, caller handles it).
- **Not verifiable from the code ⇒ a Medium phrased as a question** ("assumes `x` non-null; guaranteed by
  the caller?"), never an asserted crash.
- **Unverified premise ⇒ verify, cut to the verified part, or drop.** Never restate the PR's own text as a finding.
- **Evidence counts only at the layer it exercised** — a unit probe says nothing of the route that mounts it.
- **A Medium that should block is a mis-rated High** — re-rate; never condition an approve on it.
- **Consequence sets severity**; a tool's confidence decides only whether it is a finding at all.
- **Already an open thread** (same defect, same place, anyone's) ⇒ drop; reply on theirs if it adds evidence.
- **> ~8 inline on one PR ⇒ re-triage** against these tests; the findings file records what was dropped.

## Verifying posted findings (another reviewer's, or ours from an earlier round)

Restate the claim apart from its remedy; read the cited `path:line` at the current head; trace it.
Verdict: **confirmed** · **narrower** (real, smaller or differently caused) · **refuted** · **stale**
(fixed by a later commit) · **out of scope** (pre-existing, untouched). Re-rate on this scale. Red
flags: behavior claimed in an untouched file; `path:line` doesn't hold the code; a "risk" naming no
failing input; a pattern the repo chose deliberately; a remedy against a nonexistent signature. Only new
Critical/High/Medium post; the counts line counts new ones only.

## Inline comment shape

Prose standing alone on the thread: claim + evidence. Leads with `**Critical:**` / `**High:**` /
`**Medium:**` — the tier, never the merge consequence. No lens/tool names, scores, confidence, `severity:`
keys. Critical/High: defect + evidence, no fix shape (the author owns it). Medium: "Consider X: <why>";
single-line fix ⇒ a ` ```suggestion ` block. A finding is stated only inline, never repeated in the body.

**Anchors.** `line` = head-side line that is in the diff: from `gh pr diff <pr>` hunks, `+` and context
rows count, `-` rows don't. One off-diff anchor 422s the whole review. Off-diff ⇒ the nearest commentable
line in the same file, prose naming the real line. File outside the diff ⇒ the body names it. Spans
anchor on their last line and name the range. Never send `subject_type` or `start_line`.

## The closing event — from the counts, every round

| counts at this head | event |
|---|---|
| any Critical/High | `REQUEST_CHANGES` |
| 0 critical · 0 high, gate holds | `APPROVE` |
| 0 critical · 0 high, a gate condition open | `COMMENT`, naming the open condition |
| own PR | `COMMENT`, disposition in the counts line |

**Nothing is approved on a condition.** A standing approval made untrue by new content is superseded by
this round's `REQUEST_CHANGES`; the body says what changed.

**Approval gate** — every condition read this round; a failed read is a no:

1. 0 critical · 0 high at the head.
2. Head = the sha the findings were verified at (re-read immediately before posting).
3. Every finding of ours from earlier rounds verified fixed at this head.
4. `gh pr checks <pr>`: all passed, none pending — except names in `review.approval_gated_checks`
   (they wait on an approval and would deadlock the gate). Unlisted pending ⇒ open.
5. `mergeable` = `MERGEABLE` (`UNKNOWN` ⇒ open).
6. On a stack, the rung below approved; body carries **Stack order**.
7. No `HUMAN_NEEDED` label.

Scenario acceptance as a whole is not in the gate: it is `validate`'s, and the merge is the operator's.

## Body — this order, parts that hold only, never "none"

1. **Counts** — `**Review round <n>: x critical · y high · z medium.**` (own PR: append "— changes
   requested on the threads below" or "— clean at this head", then "(submitted as a comment event because
   GitHub does not accept an approval or a change request from the PR's own author)").
2. **Summary** — 2–3 sentences: what the change does, the read, themes. Never a per-finding list.
3. **To clear this review** — required on `REQUEST_CHANGES`: tiers by count ("the 1 High thread") + any
   show-stopper that is not line-level, once.
4. **Earlier rounds** — round ≥ 2: N of M prior threads verified fixed; what stands.
5. **Covered** — every round: surfaces read, Semgrep, suites run with real counts, what was not verified.
6. **Not a gate** — required on `APPROVE`: what it does not cover (other owners' paths, unrun suites,
   CI red inherited from the base).
7. **Needs another reviewer** — area outside competence + owning team, when it applies.
8. **Direction** — a decision the PR takes that may need to go the other way, when it applies.
9. **Stack order** — on a rung: "#N merges first".

Voice: objective, impersonal — no "I", no praise, no thanks, no tics. Internal stays internal: no spec
paths, plan jargon, slugs. Body check before sending: non-empty prose, not JSON or a tool result; a
`REQUEST_CHANGES` body has *To clear this review*; an `APPROVE` body has zero Critical/High.

## Posting

One call — inline comments inside the review, so one event:

```
gh api repos/<slug>/pulls/<pr>/reviews --method POST --input - <<'EOF'
{"commit_id":"<head sha>","event":"REQUEST_CHANGES","body":"<body, \n-escaped>",
 "comments":[{"path":"<repo-relative>","line":79,"side":"RIGHT","body":"**High:** <claim + evidence>"}]}
EOF
```

- 422 "own pull request" ⇒ nothing posted; resend the same payload as `COMMENT` with the own-PR counts line.
- Any other 422 ⇒ fix the anchor it names; never drop findings to make it pass.
- **Read back**: response `.state` + `.html_url` (the review link — never hand-built); then
  `gh api repos/<slug>/pulls/<pr>/comments --paginate --jq '[.[]|select(.pull_request_review_id==<id>)]|length'`
  = comments sent. Short ⇒ re-post each missing one singly:
  `gh api repos/<slug>/pulls/<pr>/comments --method POST --input -` with `commit_id`, `path`, `line`, `side`, `body`.
- **Reply** to a thread: same endpoint, `{"body":"…","in_reply_to":<comment id>}`.
- Exactly one review per round, clean rounds included. A request-changes stays until a later round of
  the same account supersedes it — the PM schedules that round.
