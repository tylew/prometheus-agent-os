# Stacks — the rung test, the walk, review order, reading the true head

Topology and `gt` mechanics: `branching` (`references/graphite.md`). This file: is this PR a rung, what is
the set, the order rounds run in, and reading the code under review.

## The rung test — both directions, every PR, every mode

`base ≠ default branch` is not the test.

- **Parent:** its base is another open PR's head.
- **Children:** another open PR's base is its head. This is the miss — a bottom rung has base = the default
  branch, looks standalone, and everything above depends on the review about to happen.

Walk without a checkout (`R` = `repo.slug`):

```
R=<owner>/<repo>
below() {  # ancestors, nearest first
  local n=$1 base
  while :; do
    base=$(gh pr view "$n" --repo "$R" --json baseRefName --jq .baseRefName)
    n=$(gh pr list --repo "$R" --state open --head "$base" --json number --jq '.[0].number // empty')
    [ -z "$n" ] && break; echo "$n"
  done
}
above() {  # descendants, nearest first
  local n=$1 head kid
  while :; do
    head=$(gh pr view "$n" --repo "$R" --json headRefName --jq .headRefName)
    kid=$(gh pr list --repo "$R" --state open --base "$head" --json number --jq '.[0].number // empty')
    [ -z "$kid" ] && break; echo "$kid"; n=$kid
  done
}
{ below <PR> | tail -r; echo <PR>; above <PR>; }   # whole stack, bottom rung first
```

- Both empty ⇒ genuine standalone PR. From inside a worktree `gt log --stack` prints the same set and is
  authoritative for topology.
- The PM walks it (the reviewer's allow-list does not run shell functions) and puts the set in the unit's
  `prs` token and the brief's `stack`. **Report the set before anything starts.**
- Mode triage runs against the **bottom rung**; the tip's state says nothing about its parent's.
- Author side (the stack is the worklist): [addressing-review.md](addressing-review.md) step 1.

## The bottom rung is the gate

- A child's diff is against its **parent branch, not the default branch** — review the bottom rung first,
  then up.
- **Carry on up only when the rung below closed clean (0 critical · 0 high) — approved, not merely
  reviewed.** A Critical/High at rung N rewrites rung N; `gt restack` rewrites **every sha above it**;
  anchors written against upper rungs point into a tree that will not exist.
- **Stop and say so.** Rung N blocks ⇒ its round posts; the rungs above stay unreviewed and are named *not
  reviewed — blocked on #N* in the findings file and the PM's report. A silent rung reads as a clean one.
- **Resume where it stopped:** rung N fixed + threads resolved ⇒ re-verify rung N at its new head, then
  brief N+1. Never resume from a report written before the restack.
- Post each finding on the PR whose diff introduces it; never repeat a parent's findings on its children.
- Events are per PR and ordered: a rung is not approved before the rung below; an approve on a rung carries
  **Stack order** — *#N merges first* ([findings.md](findings.md)).
- Restack force-pushes (same diff, new base) do not reset the review and do not make a round due — proven
  by patch-id ([review-loop.md](review-loop.md) → *Is a round due?*). Content changes do, and they stale an
  approval, which is recorded against a commit.

## Reading the code

**Review worktree** — detached, read-only, created by the PM, named in the brief. Fetch the true head, not
the branch:

```
git -C <repo.root> fetch origin <head-sha>          # head-sha = gh pr view <n> --json headRefOid
git -C <repo.root> worktree add $WORKSPACE/.worktrees/review-<PR> --detach <head-sha>
```

Never `--detach origin/<branch>` — it lags the real head. Read/grep there; per-PR pre-states via
`git show <sha>:<path>`; the reviewer re-pins it to the head per SKILL.md → *Read the true head*.
`open-tab.sh` links the registry's `worktree_links` (e.g. `js/node_modules`) into `review-<PR>`; other suite
dependencies — project runbooks say how; not runnable ⇒ "not run" under *Covered*. The PM removes the
worktree once the loop ends.

**Read the true head, never a stale remote-tracking ref.** Graphite force-pushes, so `origin/<branch>` and
any local worktree of it lag by one or more amends; a stale tree yields phantom findings against code the
author already changed. Tell: cited lines don't match the head's. Unsure ⇒ cross-check the hunk in
`gh pr diff <n>` before writing the finding.

**A commit is "pending" only if it descends from the PR head.** Amend + force-push leaves superseded
commits in the reflog, `refs/gt-fetch-head/*` and stale remote-tracking state. Before an action item names a
commit, `git merge-base --is-ancestor <PR-head> <X>` must hold; X sharing a parent with the head, with the
head created by a later amend ⇒ the head replaced X, and recommending X reverts the newer state.

**A head that reverses an earlier round may implement a recorded decision** — check `docs/kb/` decisions and
the story before re-raising a "fixed" finding; an accepted decision outranks the review's earlier direction
(state the decision's substance in the verdict, not its internal path).

## Comments on a stack

- Fixes go up the stack with `gt` (restack) — the author's side, never the reviewer's.
- **Disagreement:** author posts reasoning on the thread → a fresh reviewer round reconsiders → unresolved ⇒
  both positions to the operator via the PM (a hold). The story is not the venue. Settled ⇒ one reply on the
  thread states the decision, then resolve. Minor style: defer to the author.
