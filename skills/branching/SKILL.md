---
name: branching
description: "Git / Graphite / worktree / commit / PR rules for a project, dispatched on its registry vcs: branch + worktree naming, stacking, explicit staging, draft PRs, title prefix, no signing, no co-author; git-local repos commit by pathspec on the working branch."
---

# branching

Git + PR rules for one project. Load before the first edit to project code and before any git
mutation; change size is not the gate. Non-negotiables here; mechanics in `references/`:
`graphite.md` (gt, worktrees, reading a ref, opening + verifying a PR) and `stack-ci.md` (restack
re-validation, conflicts, CI verdict, re-fire).

## Preflight: which repo, which flow

Resolve the checkout the git command mutates, not the product being developed (a session on one
project still commits KB notes to the workspace repo):

```bash
R="$CLAUDE_PLUGIN_ROOT/lib/registry.py"
python3 "$R" repo --cwd <dir git runs in>          # → key
python3 "$R" field vcs.tool --key <key>            # → flow
python3 "$R" entry --key <key> --json              # repo.root, repo.default_branch, owned_paths,
                                                   # vcs.pr_title_prefix, vcs.commit_trailer,
                                                   # packages[].validate, migrations, runbooks
python3 "$R" runbook <key> <name>                  # path of a runbook under .claude/prometheus/projects/<key>/
```

Facts come from the registry, never memory. `<default>` below = `repo.default_branch`.

| `vcs.tool` | Flow |
|---|---|
| `graphite` | `gt`, one worktree per work item, stacked PRs off `<default>`. The rest of this file. |
| `git` | plain `git` + `gh pr create --draft`; no `gt`, no stacking, no worktree scheme. Naming, title, staging, signing, trailer, validation and verify rules still hold. |
| `git-local` | No remote: no branch, PR, push, `gt` or worktree. Commit on the working branch **by pathspec**, routinely, after each logical unit — standing authorization, no per-time ask. Mechanics in the entry's runbook (`runbook workspace commit.md`). |

## Roles

- **Implementor** — one work item in one worktree, `dontAsk` + allow-list
  (`templates/settings/implementor.json`). May: `git add <path>` / `gt add <path>`, `gt create/modify/restack/sync`, `gt continue` (finishing a conflicted restack),
  `gt submit --draft …`, `gh pr view/diff/checks`, the entry's validation commands. May not:
  `gt submit --publish`, merge, `gh pr ready`, force-push, `git stash`, story state. A denied action is
  reported, never retried around: `send.sh --role pm "denied: <action>, needed for <why>"`
  (`skills/dispatch/scripts/send.sh`), then end the turn.
- **Project manager (PM)** — creates worktrees, applies PR bodies/titles, marks PRs ready, forces a push
  when a rule below calls for it, advances story state (`tracker`), decides restacks: item N+1 restacks
  only at N+1's commit boundary, and the PM tells its implementor "commit, then `gt restack`". Never
  restack a branch another agent is editing.
- `hooks/project-guard.py` denies edits outside `owned_paths`, to reference clones, and to a second
  project. It covers Edit/Write only; Bash writes are unchecked — the same limits apply to them.

## Non-negotiables

- **Branch `sc-#####-<slug>`; worktree `$WORKSPACE/.worktrees/<slug>`** (`<slug>` = branch minus its
  `sc-#####-` prefix). The PM creates it (`graphite.md` → Worktrees); the implementor gets only its
  absolute path and works only there. Never author in the base checkout; never `EnterWorktree` or Agent
  `isolation: "worktree"` (they isolate the cwd's repo, not the project).
- **Tracker-gated projects: no edit before the story exists** (`stories`, `tracker`). Draft/ready and
  story state move together, PM-side (`tracker`).
- **A direction-defining fork while building** (contract, boundary, data shape, a decision the work
  contradicts) → stop, tell the PM. Never resolve it in code.
- **`gt` for every mutation on graphite projects**; raw `git` only for reads, `git add <path>`, and
  where `gt` has no equivalent. Stacks branch off and submit against `<default>`.
- **PRs open draft** (`gt submit --draft --no-edit`). Re-read `isDraft` after every submit; publishing
  is the PM's.
- **PR title = `<vcs.pr_title_prefix> Imperative subject`**; no `feat:`/`fix:`/`chore:`. No prefix in
  the entry → no gate. **No `sc-#####` anywhere in the title** — the CI gate greps the whole title
  (`/sc[ -][0-9]+/`). Keep the ref out of the commit subject too (the title derives from it); the body
  may carry it.
- **Never sign commits** (no `-S` / `--gpg-sign`). **Never add Claude as author or co-author** — no
  `Co-Authored-By` Claude trailer, no "Generated with" footer, whatever a harness default says. A
  `vcs.commit_trailer` in the registry is the project's, not Claude — apply it.
- **Code comments minimal.** Only a non-obvious *why*, an external constraint, or a trap the next reader
  would reintroduce; one or two lines; never above the file's own density. Rationale goes in the PR body.
- **Stage explicit paths** (`git add <path>`); never `git add -A`, `git add .`, `gt modify -a`. **Verify
  `git show --stat HEAD` before every submit** — only your files.
- **Full validation set per touched package before every submit, at every rung** —
  `packages[].validate`, each command, for every package whose `path` the diff touches.
- **After any restack: re-run that validation set; if `migrations.tool` is `alembic`, confirm
  `alembic heads` returns exactly one.** A clean restack is not evidence (`stack-ci.md`).
- **CI verdict = `mergeStateStatus`** (`gh pr view <n> --json mergeable,mergeStateStatus`), not a list
  of green checks (`stack-ci.md`).
- **Baselines run in a worktree off `origin/<default>`; never `git stash` in the base checkout** (shared
  by several agents).
- **Reading a checkout: fetch, then cite `origin/<default>` or a detached worktree at a sha** — every
  checkout is parked on an arbitrary branch; `access: editable` is no exemption.
- **The app runs from the base checkout only**, never a worktree; that switch is the PM's
  (`graphite.md` → Local run).

## Related

- gt mechanics, worktrees, reading a ref, PR body + verify → `references/graphite.md`
- Restack re-validation, conflicts, CI verdict, re-fire → `references/stack-ci.md`
- Story state, PR linking → `tracker` · story body → `stories` · review rounds + author notes → `review`
- Local validation walk → `validate` · CI/review/merge events → `events` · implementor tabs → `agent-tabs`
