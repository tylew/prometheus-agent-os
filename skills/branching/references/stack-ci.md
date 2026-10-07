# Restack re-validation & CI verdict

## Restack is not done when `gt` says it is

A rebase resolves text only. After any restack or rebase, re-run `packages[].validate` on **every branch
of the stack** — each PR is gated alone; the middle can fail while bottom and tip pass. Restack
**bottom-up, `gt restack` from each branch's own worktree**: `gt restack` skips a branch checked out in
another worktree and reports success for the rest. A commit added lower afterwards invalidates the
children — restack upward again before submitting. The PM sequences this (`SKILL.md` → Roles).

Recurring shapes:

- **Semantic conflict in files neither side touched** — trunk code calls a function the branch renamed,
  or builds a fixture missing a field the branch made required. Nothing conflicts; the type check fails.
- **Second migration head** (`migrations.tool: alembic`) — another revision landed on `<default>` off
  the same parent. `alembic upgrade head` fails "Multiple head revisions are present"; a fresh DB cannot
  migrate. Fix: re-parent the branch's revision onto the new head (`Revises:` in the docstring **and**
  `down_revision`), not a merge revision. Confirm `alembic heads` returns exactly one, every restack.
  Run the migrate step visibly — piped to `/dev/null` a second head is a bare non-zero exit.
- **Both sides added at one anchor and the merge kept both** — concatenated docstring tails, a duplicate
  import, a guard re-added below its twin, a comment pair cut mid-clause. Happens on auto-merged hunks
  too. Re-read comment blocks, docstrings and import lists of every file the restack touched.
- **Markers committed after a "resolved" conflict.** `gt add` takes one file per call; given two it
  stages one, and `gt continue` can commit the other with markers while `git status` reads clean. After
  a restack that reported conflicts:
  ```
  for c in $(git rev-list <parent-head>..HEAD); do
    git grep -q -E "^(<<<<<<<|>>>>>>>) " $c -- <touched dirs> && echo "MARKERS $c"
  done
  ```
  Repair the commit that introduced it, not the tip: `git checkout --detach <bad-sha>` → fix →
  `git commit --amend --no-edit -- <paths>` → `git cherry-pick <each sha above, oldest first>` →
  `git branch -f <branch> HEAD` → `git checkout <branch>` (no `rebase -i` here).

Implementor: a restack that stops on conflicts, or any repair above outside the allow-list → report to
the PM with the conflicted paths; never work around a denial.

## CI verdict

**Verdict = `mergeStateStatus`, not green checks.** External CI (e.g. Buildkite) reports commit
*statuses* (`context`); GitHub Actions reports check runs (`name`). A rollup filtered on `.name` drops
every status — a blocked PR reads all-green. Read both:

```
gh pr view <n> --json mergeable,mergeStateStatus
gh api repos/<owner>/<repo>/commits/<sha>/status --jq '{state, statuses: [.statuses[]|{context,state}]}'
```

- Old FAILURE rows stay in `statusCheckRollup` after a fix: judge the newest run per check name.
- Checks in `review.approval_gated_checks` stay pending until approval — expected on a draft.
- **`BLOCKED` with everything visible green** = a required status never reported (an umbrella check
  fails on a *missing* status). A step that got no agent ("Timed Out — Waited 10s") is infrastructure:
  confirm by running its command locally on the PR head, then retry that job in the CI (Buildkite:
  `get_build_failure_summary` with the build from the status `target_url`, then `retry_job`). The GitHub
  API re-requests Actions runs only.
- An artifact/image-push step red while every test and lint lane is green = transient push failure;
  retry that job.
- **`pending` for tens of minutes is usually a queue.** Check the pipeline, not the PR: statuses of a few
  other open PRs' heads. Recent finishes → capacity exists; none → agents scarce, and a re-fire only
  rejoins the back of the queue.
- `Build #N canceled by <person>` = superseded by a newer sha on the branch (a chain = own re-pushes).
- A retry build may show fewer lanes when CI skips lanes already passed for an unchanged tree; read the
  earlier build for the missing lane.
- Whether an approval survives a force-push is per repo: check
  `gh api repos/<owner>/<repo>/issues/<n>/timeline`.

## Re-firing CI (PM — needs a force push)

Needs a new sha; one-shot per branch. `gh pr close` + `reopen` starts nothing; re-pushing the same sha is
a no-op. Only when the queue check shows capacity and the branch was not re-fired before:

```
git rev-parse HEAD^{tree}          # record
git commit --amend --no-edit
git rev-parse HEAD^{tree}          # must match
gt submit --no-edit --update-only --force
```

The amend cancels the running build. Amending a stack's bottom = restack everything above, from each
branch's own worktree.
