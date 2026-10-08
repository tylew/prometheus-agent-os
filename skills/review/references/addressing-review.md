# Addressing review on the operator's own PR — PM + implementor

Review landed on a PR this unit authored. The PM triages, decides, replies and resolves; the implementor
fixes and validates (it cannot post to GitHub). Self-review before requesting a human:
[self-review.md](self-review.md).

**Two loops.** Steps 1–7 are one **round**: one review's comments, worked to a push. Step 8 is the outer
loop: the author side holds for the next round until the PR **merges, closes, or goes on a hold** — exactly
as the reviewer's loop does ([review-loop.md](review-loop.md) → *Ending*). A push ends a round, never the
loop.

**A `CHANGES_REQUESTED` with Critical/High standing is the normal state**, not an escalation. The
reviewer's own loop clears it by approving once the counts reach zero; the author's job is the round.

## The round

1. **Ingest every comment — across the whole stack.** One pass posts on every rung; a tip with every thread
   resolved says nothing about its parent. Walk both directions ([stacks.md](stacks.md)), then per PR:
   ```
   gh pr view <pr> --json reviews,comments,reviewDecision
   gh api repos/<slug>/pulls/<pr>/comments --paginate        # inline threads: path/line/body/id
   gh api graphql -f query='query{repository(owner:"<owner>",name:"<repo>"){pullRequest(number:<pr>){
     reviewThreads(first:100){nodes{id isResolved path comments(first:1){nodes{databaseId}}}}}}}'
   # unresolved set across all rungs IS the worklist; keep each thread's `id` for step 5
   ```
   Nothing is worked until the whole set is in view. Work runs bottom-up.

2. **Triage the whole set before fixing anything** — [triage.md](triage.md) A–D, then the PM's *Review
   findings* defaults (`agents/project-manager.md`). Declines and refutations are outcomes: each gets an
   evidence reply + resolve at step 5. Only *Design-affecting* goes to step 3; everything else to step 4.
   **A finding whose disposition turns on what the product should do** — the end behavior, not the
   mechanism — goes to the operator before its fix, never settled by the PM: one sentence per fork, the
   built behavior as the first option, every fork in one batched question once the independent fixes have
   landed and validated. A behavior the design already settled that the review re-questions with *new*
   information is asked the same way, the design's answer recommended. The thread reply states the answer
   as confirmed, with the date.

3. **Design-affecting → PM / operator before any code.** The confirmed spec (`design.md`, `plan.md`) is a
   read-only contract: the delta is a decision record (`templates/decision-record.md` →
   `send.sh --role librarian`), and a change to Scenarios or acceptance criteria goes to the planner
   (`stories`). Material change ⇒ the story moves back to `in_development` (`tracker`).

4. **Fix one at a time — never batch.** The PM routes each finding to the item's implementor: one finding →
   one change → touched-package validation (`packages[].validate`). The implementor reports, per thread, the
   commit and what changed. One logical change per finding keeps thread ↔ diff honest.

5. **Reply + resolve at disposition time** *(home of the author side)*. Fix ⇒ what changed; decline /
   refutation / stale ⇒ the evidence that settles it. The reply path needs the **PR number** — the
   `/pulls/comments/<id>/replies` form 404s:
   ```
   gh api repos/<slug>/pulls/<pr>/comments/<comment_id>/replies -F body=@<file>
   gh api graphql -f query='mutation{resolveReviewThread(input:{threadId:"<PRRT_…>"}){thread{isResolved}}}'
   ```
   `-F body=@<file>` reads the file; `-f` posts the path itself. Body checks: [findings.md](findings.md) →
   *Every outward body*. **On a stack, name the commit from the pushed PR head, not local `HEAD`**: a fix
   below the tip forces `gt restack`, which rewrites every sha above it. Read it back after the submit
   (`gh pr view <pr> --json headRefOid`), or describe the change without a sha and let the round comment
   carry `<reviewed-sha> → <new-head-sha>`. A restack forced after the replies went out ⇒ edit each:
   `gh api -X PATCH repos/<slug>/pulls/comments/<id> -F body=@<file>`.

6. **Keep the story's contract true; do not narrate the review on it.** Accept/declines and rationale stay on
   the PR. Review changed **what ships** ⇒ the planner corrects Scenarios/AC; one comment only if scope/AC
   moved (`tracker` → board case 1).

7. **Close the round, rung by rung.** Every thread on a rung resolved + validation green ⇒ the implementor
   submits (`branching`); the PM posts **one round comment** (`gh pr comment <pr> --body-file <file>`):
   - heading `Review round addressed — <reviewed-sha> → <new-head-sha>`; `@` every reviewer whose findings
     it addresses (logins from `gh api repos/<slug>/pulls/<pr>/reviews --paginate --jq '.[].user.login'`,
     deduped — a resolved thread is not a notification they see);
   - the verdict spread (code changes · decisions · declines/refutations, summing to N); each Critical/High
     one bullet, what held and what changed; Mediums/Lows grouped by cause; each decision with its cost and
     what now pins it; each decline with its evidence; validation with real counts and CI state on this
     head (never imply a pending check passed); PR-description claims this round made false, corrected.
   - ends with the signature line (system prompt → *Signing outward content*): the dispatcher reads an
     unsigned post from the operator's account as the operator's own and wakes the PM with it.

   Then:
   - **This loop's own `CHANGES_REQUESTED` is not dismissed** — its next round verifies and supersedes it.
   - **Another account's** `CHANGES_REQUESTED` whose last finding this round resolved is **dismissed now**:
     id from `gh api repos/<slug>/pulls/<pr>/reviews --jq '.[]|select(.state=="CHANGES_REQUESTED")|.id'`,
     `gh api -X PUT repos/<slug>/pulls/<pr>/reviews/<id>/dismissals -F message=@<file>` (message names the
     round comment), read back `.state == "DISMISSED"`.
   - **Re-request**: `gt submit --reviewers <handle>`; on an already-pushed head that submit is a no-op and
     adds no reviewer — verify `gh api repos/<slug>/pulls/<pr>/requested_reviewers`; missing ⇒
     `gh api -X POST repos/<slug>/pulls/<pr>/requested_reviewers -f 'reviewers[]=<handle>'`. After any
     submit, `gh pr view <pr> --json isDraft` — a plain submit un-drafts.
   - **On a stack** a parent's fixes rewrite every sha above: each child restacks at its own commit boundary
     (`agents/project-manager.md` → *Stacked work*), re-runs its validation, and passes the stack checks in
     `branching` (`references/stack-ci.md`) before submitting. The round is not done while a lower rung
     still carries standing findings.
   - State stays `ready_for_review` (step 3 sent it back ⇒ advancing again on re-push is the gate). Never
     approve or merge the operator's own PR.

   **A push with nothing else — no reply, no round comment — is not a round.** The reviewer's loop reviews
   the delta against threads left unanswered, and they come back.

8. **Hold for the next round — do not end here.** Re-requesting is a wait, not a handoff: end the turn; the
   dispatcher wakes the PM on a review, comment, new commits or merge. A round is due again on the reviewer's
   three triggers read from the author's side ([review-loop.md](review-loop.md) → *Is a round due?*): new
   findings, a reply on a thread the author owns, a re-request of the operator.

## Rules

- **A review pass fixes; it does not build. "Accept, no change" is a disposition.** A finding raising a
  product question is most often accepted as-is and recorded as a decision; scoped work follows only if the
  operator decides otherwise. **Never net-new UI between two fix commits** — a feature invented mid-pass
  has no adversary. A guard belongs at the entry point whose reachability is the concern, not on the shared
  path.
- **No code moves on an unverified finding** — reviewer confidence is not evidence ([triage.md](triage.md)).
  Fixing to clear a thread lands unreviewed changes and hides that the finding was wrong.
- **Stale code docs found during a fix** are their own proposed story (planner), never folded into the fix.
- **A settled disagreement is written down on the thread** — taken to the operator ⇒ one reply stating the
  decision, then resolve; the long thread is not continued.
- **"Needs a person" / `HUMAN_NEEDED` = the PM guides the operator through it, never a parked wait.** The
  person is the stakeholder (the operator); the PM is their guide. Gather what the check needs with its own
  tools (read the change, run it on a scratch DB / local dev, read-only probes), put a human-readable
  walkthrough to the operator one point at a time (in place when present, else via the seat), and take the
  operator's verdict as the person's. Confirmed ⇒ say so on the PR, dated, and clear the label when the
  setter's text says a person's say clears it; held ⇒ it stays. The verdict is the operator's, never the PM's.
- **Do not advance past the lane** — re-request is the author side's; approve, merge and the move to
  `completed` are the reviewer's / operator's.
