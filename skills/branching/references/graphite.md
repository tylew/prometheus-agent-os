# Graphite, worktrees, PRs

`vcs.tool: graphite` mechanics. `<root>` = `repo.root`, `<default>` = `repo.default_branch`, from the
registry. Restack + CI → `stack-ci.md`.

## gt

- Commands: `gt create` (new branch + commit) · `gt modify` (amend) · `gt modify -c` (new commit on the
  current branch) · `gt restack` / `gt sync` (rebase on an updated trunk) · `gt submit --draft` (push +
  open/update PRs). Overrides any plain-git / `gh pr create` step a tool suggests.
- No persistent integration branch; stacking is branch-on-branch off `<default>`.
- **`gt modify -m` amends the tip — it does not add a commit.** It rewrites the tip's message and folds
  the staged changes in (tell: `3 files changed` on a one-file staging). New commit: `git add <paths>`
  then `gt modify -c -m "<msg>"`. Recovery (PM): old sha from the reflog →
  `git show -s --format=%B <old-sha> > msg.txt`, `git reset --soft <commit-below>`, `git reset`,
  re-commit each set by pathspec in order.
- Amend with nothing new: stage explicitly, then bare `gt modify`.
- `gt` has no read surface: `gh pr view|diff --json …`, `gh api`.

## Draft flag: re-read after every submit

`--draft` applies at PR creation only. A later submit can un-draft the PR (notifies reviewers, desyncs
the story). After every submit: `gh pr view <n> --json isDraft`. `false` while the story is not
ready → implementor reports it; PM runs `gh pr ready <n> --undo`.

## Submit refusals

- **"trunk branch is out of date and could not be updated"** — local `<default>` lags; not `gt sync`
  (it prompts to delete branches other worktrees hold):
  ```
  git fetch -q origin <default> && git merge-base --is-ancestor <default> origin/<default> && echo ff-ok
  git fetch -q origin <default>:<default>   # refuses if checked out somewhere — look first
  gt submit --draft --update-only --no-edit
  ```
- **"Updated remotely outside of Graphite"** — something moved the branch without `gt`. PM only:
  ```
  git fetch origin <branch>
  git merge-base --is-ancestor origin/<branch> HEAD && echo fast-forward
  git log --oneline origin/<branch>..HEAD
  gt submit --no-edit --update-only --force
  ```
  Ancestor check fails → genuinely diverged: reconcile, never `--force`.
- **Parent merged** (squash-merge: its commits never become ancestors of `<default>`). `gt sync` says
  "does not need to be restacked" while the child's PR re-includes the parent's diff. Check
  `git log origin/<default>..HEAD` shows only the child's commits; else PM runs `gt move --onto <default>`
  from the child's worktree, then full re-validation (`stack-ci.md`). A following "updated remotely"
  with identical head content = nothing to recover.

## Divergence and reading a ref

- Checkouts may be shallow: `git merge-base` / `rev-list --count` against `origin/<default>` lie at the
  boundary. Ask GitHub: `gh pr view --json mergeable,mergeStateStatus`, `gh pr diff --name-only`. Fetch
  fresh first; local `origin/*` goes stale between sessions.
- Never conclude from the parked tree; `git pull` refreshes only the parked branch. Fetch, then read a
  pinned ref:
  ```
  git -C <root> fetch origin <default>
  git -C <root> fetch origin pull/<PR>/head:refs/remotes/origin/pr/<PR> --force   # named ref, not FETCH_HEAD
  git -C <root> worktree add $WORKSPACE/.worktrees/review-<PR> --detach <sha>
  ```
  `refs/prfetch/*` is Graphite's namespace — never fetch into it. A PR head moves: re-fetch before
  scoping, testing or recording a finding, and state the sha analysed (`gh pr view --json headRefOid`).

## Worktrees (PM creates, implementor works)

```
git -C <root> fetch origin <default>
git -C <root> worktree add $WORKSPACE/.worktrees/<slug> -b sc-#####-<slug> origin/<default>
git -C $WORKSPACE/.worktrees/<slug> rev-parse --show-toplevel     # must equal the worktree
(builtin cd $WORKSPACE/.worktrees/<slug> && gt track --parent <default>)
```

- Without `gt track` the first submit refuses ("untracked branch"). `gt track` counts against a stale
  local `<default>`; real scope = `git log origin/<default>..HEAD`.
- Stacked item: `-b <branch> <parent-branch>` and `gt track --parent <parent-branch>`.
- Re-attach an existing branch: `git -C <root> worktree add $WORKSPACE/.worktrees/<slug> <branch>`.
  List: `git -C <root> worktree list`. A worktree made elsewhere: `git worktree move` it into
  `.worktrees/`.
- Brief the implementor with the worktree's absolute path only — never `root` + `owned_paths`, which
  resolve to the base checkout and the edit lands there silently.
- Dependencies: JS `node_modules` symlinked from the base checkout (`open-tab.sh` does it from the registry's
  `worktree_links`), never reinstalled; Python gets its own
  venv (`uv sync` in the worktree's package dir) — never point `UV_PROJECT_ENVIRONMENT` at the base's
  `.venv`. Build/test variables a worktree needs (e.g. a monorepo-root override for `make`): the
  project's runbooks.
- Never leave a suite running in a worktree about to be rewritten (restack, amend, checkout): it reads
  swapped files mid-run. Kill it, rewrite, validate once on the final tree.

## Local run (PM)

The app runs from the base checkout only. To serve a worktree's branch: finish every `gt` op first
(submit, body, publish) — `gt` against a branch whose worktree was released can `reset --hard` the base
onto an unrelated `refs/prfetch/*` ref and report "(updated)". Then `git -C <wt> switch --detach`,
`git -C <root> switch <branch>`, restart from the base. On the base the branch is run-only; a later `gt`
op moves it back to its worktree first. Walk → `validate`.

## Opening a PR

1. **Validate** — `packages[].validate` in full for every touched package, from the worktree, per the
   project's runbook (cwd, env). Tests alone are not the set: a lint failure low in a stack reds every PR
   above. On a stack, validate at every rung the change reaches; fix at the rung that introduced it.
2. **Commit** — on a story's rung, each commit is a skeleton, a tests or a code commit, never tests and
   code together (`lib/proof.py`); `gt create` for the first, `gt modify -c` after. Staged paths only; subject = prefix-free imperative, no `sc-#####`; `vcs.commit_trailer`
   appended if set. `git show --stat HEAD`.
3. **Submit** — `gt submit --draft --no-edit`. Then `gh pr view <n> --json title` (title rule: `SKILL.md`)
   and `isDraft`.
4. **Body** — `gt submit` leaves the repo's empty template. Implementor writes the body file beside its
   report; PM applies `gh pr edit <n> --body-file <file>` (and `--title` if wrong). Headings follow the
   repo's own `.github/pull_request_template.md`; absent one: *Shortcut issue* · *What changed and why* ·
   *Acceptance criteria* (one bullet per story scenario, name verbatim, how this PR makes it hold) ·
   *Automated testing* (tests added + each validation command run, real counts) · *Scenario tests* (every PR
the whole table: one row per scenario, `passing` · `passing, held before: <why>` · `in #<n>` · `manual:
<proof, where>`, exactly one row per scenario not `in #<n>`; a test rewritten after its code says why) ·
*Manual testing*
   (optional; checkbox ticked only by an operator walk, `validate`) · *Screenshot or Video Demo*
   (required when a user-visible surface changed, else omit) · *Risks* (required; `None — <why>` is
   valid) · *Notes for reviewer*. The bottom PR ends with the IDR block
   (`python3 <plugin>/lib/idr.py block <body.md> <story_dir>/idr.md`), refreshed whenever the
   IDR changes.
   - **Exactly one `sc-#####`** — the delivered story; every ref moves that story and links the PR. A
     stacked sibling is cited by PR URL. The link fires on the first `gh pr edit` and cannot be undone:
     get the body right first.
   - Objective voice, no first person, no internal-doc names or jargon — describe the mechanism.
   - Omit an empty optional section.
5. **Verify after every submit** (including `--update-only` and the PM's `--publish`):
   `gh pr view <n> --json body,isDraft,title,commits` + `gh pr diff <n> --name-only` — your files, your
   commits, one ref, required sections filled. Title, body and draft flag can read right while the
   branch points at another stack.
6. **Report** to the PM (path list, validation result, PR link). Author inline notes, publish, story
   state → `review`, PM, `tracker`.
