# The review loop — the PM's side

**The loop belongs to the PM, not to whoever runs a round.** *(Home.)* A reviewer runs **one round** in a
fresh `review-<pr>` session and ends — the design, not a half-review. The PM briefs round 1, writes the
story line, resolves threads, puts on and clears holds, and closes the unit. Later rounds open themselves
(`prometheus:dispatch` → *Review rounds open themselves*): on a teammate's PR when new commits settle, on
the operator's own PR when the PM runs `rounds.sh next <pr>` after its round comment; the opened reviewer
runs *Is a round due?* first.
It never polls, arms a `Monitor`, runs `/loop` or background-waits: it ends its turn, and dispatcher event
lines (new commits, CI terminal, reviews, comments, merged/closed, agent state, heartbeat) wake it
(`events`). Every PR the loop holds sits in the unit's `prs` token before its first round, so its events
route here.

## Review units

The dispatcher creates a `review` unit for the whole stack (`prometheus:dispatch`) when:

- **(a)** a PR requests the operator's review — brief `requested: yes`;
- **(b)** a teammate's PR touches the project's `owned_paths` with no request — `requested: no`
  ([*Unrequested review*](#unrequested-review)).

Authors in `review.ignore_authors` never get one. Rounds run bottom-up per stack order
([stacks.md](stacks.md)); report the stack set to the seat before round 1 — an ask about one PR is owed
the stack.

## Round 1

Walk the stack ([stacks.md](stacks.md)). PR body missing on any rung ⇒ one comment asking for a
description, `@`-tagging the author (on a stack: one comment on the tip naming each PR), and no round until
it lands or the operator says proceed. Otherwise create the read-only review worktree
([stacks.md](stacks.md) → *Reading the code*), brief the bottom rung (`templates/reviewer-brief.md`), open
`review-<pr>` (`agent-tabs`, `lib/launch.sh reviewer`).

Brief fields the PM reads fresh: `open_threads` (unresolved threads — GraphQL below), the prior rounds'
findings files, `requested` (pending request of the operator: `gh pr view <pr> --json reviewRequests`),
`deep` (only when the operator opted in for this PR; never set on the PM's own judgement).

## Is a round due?

Run by the reviewer of a dispatcher-opened round, and by the PM for a trigger with no new commits (author
reply, re-request ⇒ `rounds.sh next <pr>`). **Labels first, every time:**
`gh pr view <pr> --json labels --jq '[.labels[].name]'`. A failed read is a hold, not an absence.

| label | means | the loop |
|---|---|---|
| `NO_AUTO_REVIEW` | the author asked every loop to leave the PR alone | no round, ever; never cleared by this loop |
| `HUMAN_NEEDED` | a person has to act first — whoever set it | read on, act on nothing, never approve; on the operator's own PR the PM guides the operator through it ([addressing-review.md](addressing-review.md) → *Rules*) |

Then only these three, against the newest findings file. None ⇒ **nothing is posted** — not a reply, not a
"still open" nudge, not a fresh pass.

| trigger | how it is read |
|---|---|
| the head changed **in content** | `headRefOid` moved **and** the diff is not the same diff (below) |
| the author replied on one of **our** threads | a thread comment that is not the opener and not in any findings file's ids |
| review re-requested of the operator | a pending request newer than the last round (`reviewRequests`, or `gh api repos/<slug>/pulls/<pr>/requested_reviewers`) |

**Pure restack ⇒ no round, and a standing approval still covers the head.** Graphite force-pushes on every
restack. Compare `gh pr diff <pr> | git patch-id --stable` at the reviewed head (saved diff) and now: same ⇒
same diff. Different, or not computable ⇒ changed; **not computable is never a pass.**

**Round in progress** — a `review-<pr>` tab working, or the newest findings file without a review id ⇒
not due; never brief a second session onto the same round.

**Re-request handling.** A re-request with no content change is still a trigger: the round re-verifies our
threads against the author's replies and closes on the event the counts decide. GitHub clears the request
when the round posts. A re-request of a stack rung above one that is not closed clean waits for that rung.

## A follow-up round

The dispatcher closes the finished `review-<pr>` tab and briefs a **fresh** reviewer session (one round per
session) from the last brief, round + 1; the reviewer reads the prior findings files and `open_threads`
fresh. The reviewer re-checks our threads first, then reviews
only what moved (SKILL.md → *Earlier rounds*).

## After a round lands

The reviewer's `send.sh` line wakes the PM. Then:

1. **Verify, don't relay.** `gh api repos/<slug>/pulls/<pr>/reviews --paginate --jq '.[-1] | "\(.user.login)\t\(.state)\t\(.html_url)"'`
   (`--paginate` required — otherwise the newest is the one cut). State matches the reported event; the
   findings file's status reads `posted`. Mismatch ⇒ treat as a failed round.
2. **Resolve threads** the findings file lists under *Threads to resolve* — **only threads this loop
   opened** (ids in a findings file). The loop and the operator post from one login; in doubt, it is someone
   else's and stays open.
   ```
   gh api graphql -f query='query{repository(owner:"<owner>",name:"<repo>"){pullRequest(number:<pr>){
     reviewThreads(first:100){nodes{id isResolved comments(first:1){nodes{databaseId}}}}}}}' \
     --jq '.data.repository.pullRequest.reviewThreads.nodes[] | "\(.comments.nodes[0].databaseId) \(.id) \(.isResolved)"'
   gh api graphql -f query='mutation{resolveReviewThread(input:{threadId:"<PRRT_…>"}){thread{isResolved}}}'
   ```
3. **Story counts line** — one per round, on the story the PR delivers (branch `sc-#####-` prefix, else the
   tracker's lookup by PR URL), `tracker` → board case 5:
   `Review round N: x critical · y high · z medium — <changes requested | approved | comment: <condition>> — <review html_url>`.
   No round moves the story's state.
4. **Needs a call** items → the PM decides disputes between agents; behavior and scope go to the operator
   (one sentence per fork, options as choices); holds per below.
5. Next rung: closed clean ⇒ brief the rung above; else it stays *not reviewed — blocked on #N*.
6. Status line to the seat (`templates/pm-report.md`): rounds so far, counts, threads closed, what was held
   back, the event's URL and the head it covers, what could not be verified, "loop open" — never a sign-off.

## A hold

Read on, act on nothing — no briefs, no replies, no approve — until the operator clears it. Put one on, and
put the fork to the operator (via the seat unless present; one sentence, built behavior named, options as
choices), for:

- **a finding the author disputes**, or any open question the code cannot settle;
- **a finding whose disposition turns on what the product should do** — the end behavior, not the
  mechanism;
- **non-convergence**: round 3 on one PR closes with Critical/High still standing — review and author are
  not converging, and another round of the same is not the answer; no round 4 without the operator;
- **a finding outside competence** (another team's owned paths, shared infra) — the round still posts with
  **Needs another reviewer**;
- **failing closed**: `gh` failing or its auth expired, a reviewer round that errored or reported something
  that will not parse. A failed round is never "no findings" and never approves. Notify once per cause; say
  when it clears;
- **the operator puts it on hold.**

**No round opens itself on a held PR**: `rounds.sh hold <pr>` with every hold, `--off` when it clears.

**Published as a label.** Putting a hold on ⇒ `gh pr edit <pr> --repo <slug> --add-label HUMAN_NEEDED`, in
the same turn as the fork; what a person is needed for stays in the round's own text. Clearing: only a hold
this loop set, only once the operator cleared it: `--remove-label HUMAN_NEEDED`. A label this loop did not
set is cleared by whoever set it. A person removing it by hand clears the hold — do not put it back for the
same cause.

## Unrequested review

Unit kind (b), brief `requested: no`. The body opens by saying the review was not requested and why it was
posted ([findings.md](findings.md) → *Body*); the event is `COMMENT` unless Critical/High stand
(`REQUEST_CHANGES`); it never approves. Follow-up rounds fire on content change or an author reply on our
thread only. A request of the operator arriving later switches the unit to `requested: yes` from the next
round. The author asking the loop to stop ⇒ treat as `NO_AUTO_REVIEW`; put it to the operator.

## A standing approval that stops being true

Content changed after an approve and the gate no longer holds ⇒ the next round's `REQUEST_CHANGES`
supersedes it from the same account, saying what changed. Never leave an approval describing a tree that no
longer exists.

## Ending — merge, close, or a hold; never a round's own event

*(Home.)* Three terminal states: **merged**, **closed**, **on a hold the operator owns**. Every round —
request-changes, comment and approve alike — is followed by the PM ending its turn and waking on the next
event. The clean round is the one most likely mistaken for the end: its Mediums are open threads the author
answers next, and a push after it can make the approval untrue.

Every PR in the unit merged or closed ⇒ close the `review-<pr>` tabs, remove the review worktree, report to
the seat, `close-unit.sh <workspace-id>` (`unit-workspaces`). **Approving is not merging**: the merge is the
operator's; told to merge, merge, and verify it landed (`gh pr view <pr> --json state` = `MERGED`; `gt merge`
reports success before GitHub does). During a review no one in the loop commits or pushes a fix to the PR
under review — the finding posts, the author changes the code.

## State — the findings files

No separate state file. The findings files (`<state>/reviews/<owner>-<repo>-<pr>-r<round>.md`) record per
round: head reviewed, review id + URL, thread ids opened, status. Every wake reads the newest before acting;
a round at the current head with status `posted` makes a repeated wake a no-op.

**An earlier loop's reviews are adopted, not duplicated.** A review from the operator's login whose body
opens with the counts line, at a head no findings file records ⇒ the reviewer records it as a round
(SKILL.md → *Preconditions*); its threads become ours. A thread the operator wrote by hand belongs to no such
review and stays someone else's.

## Own PR

The loop runs the same way on an operator-authored PR (self-review, or a review unit over the operator's
own stack): the event is `COMMENT` every round, disposition in the counts line ([findings.md](findings.md)).
The gate still decides which disposition the body states. The author side is
[addressing-review.md](addressing-review.md).
