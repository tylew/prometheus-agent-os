# Deep review — a Workflow, operator opt-in only

The standard pass ([review-pass.md](review-pass.md)) is one specialist fan-out with the reviewer verifying
by hand; it runs out of room on a large PR or a long stack. Deep mode: one agent per dimension,
**every candidate adversarially verified against real code** before it counts, a consolidated per-PR
verdict — local and resumable. Not `code-review ultra` (human-triggered, billed, cloud).

**Gate:** runs only when the brief says `deep: true` — the operator opted in for this PR. Never
self-selected, never auto-fired; a PR that looks too big without it ⇒ say so under *Needs a call*.

## The pipeline (per PR, bottom-up, one PR fully before the next)

1. **Review** — one agent per dimension, in parallel:
   - toolkit-backed, `agentType` **plugin-namespaced** exactly as the Agent registry lists it (a bare name
     does not resolve and silently costs the dimension its specialist): `code-quality` →
     `pr-review-toolkit:code-reviewer`, `error-handling` → `pr-review-toolkit:silent-failure-hunter`,
     `tests` → `pr-review-toolkit:pr-test-analyzer`, `comments` → `pr-review-toolkit:comment-analyzer`
     (truth and volume), `types` → `pr-review-toolkit:type-design-analyzer` (only where a type changes);
   - project dimensions — inline reviewers (default agent), one per deep dimension the project's review
     runbooks name ([review-pass.md](review-pass.md) step 2).
   Each prompt carries the target guard: worktree absolute path, `owned_paths`, `samples/` read-only
   reference, read-only (`gh pr diff`, `gh pr view`, git, Read; post nothing); the matching lenses; "diff
   against its own PR base (the parent branch), read surrounding code for data flow, report only issues
   this PR introduces, fewer high-confidence findings". Return schema per finding: `title`, `file`, `line`,
   `severity` (Critical/High/Medium/Low/Note), `detail`.
2. **Verify** — every candidate to a fresh agent told to **refute** it: substantiated only with an exact
   `file:line` in real code proving the behavior; inferred from a name, comment or plausible story ⇒
   dropped; real but pre-existing ⇒ dropped; severity re-rated. Pipeline it: a dimension's findings verify
   as soon as its review lands.
3. **Consolidate** — per PR: one-line read, counts by severity (Critical/High/Medium published; Low/Note
   held back, counted separately), every publishable finding with `file:line`, **To clear this review**
   when any Critical/High stands, count of dropped candidates. Never a conditional approval.

Every agent is read-only; the Workflow posts nothing and returns data.

## Running it

1. Write the script with the Write tool to
   `<state_dir>/reviews/deep-<owner>-<repo>-<pr>.mjs` per the
   `workflow-authoring` skill (load it first): `meta` with the three phases, `args` = `{repo, prs (bottom-up),
   worktree, ownedPaths, lenses: [{path, applies_to}], dimensions?}`, the pipeline above. A `dimensions`
   subset logs which ran and names any unknown key — a narrowed review otherwise reads like a clean one.
2. `Workflow({scriptPath: "<absolute path>", args: {…}})`. Resumable: re-invoke with `resumeFromRunId`
   (same script + args → cached prefix).
3. **Act on the return** `{repo, reviewed: [{pr, counts, dropped, findings, summary}]}` — an input, never a
   body. Transcribe each finding (`file` → `path`, `detail` → body prose, severity re-rated through the
   boundary tests), run the before-posting checks, and post per [findings.md](findings.md). Deep mode is one
   round of the loop like any other: the counts pick the event; it never advances the story or merges.
