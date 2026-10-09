# The review pass — one round's reading and rating

Run by the reviewer, after the SKILL.md preconditions. Rating, posting and the event:
[findings.md](findings.md). When the next round runs: the PM ([review-loop.md](review-loop.md)).

**Command form** — `prometheus:dispatch` (the project runbook says which make targets and flags).

## 0. Context surfaces — before the diff

Intent comes from these, never reverse-engineered from the diff:

- the brief's scenarios (verbatim) and story scope;
- the PR body and every thread (`gh pr view`, the comments + reviews APIs); on a stack, every rung's body;
- the spec dir for the area (`registry.py field docs.specs --key <k>`) and `docs/kb/` — read for intent,
  never cited outward;
- calibration memos, if present: `<state_dir>/reviews/calibration.md`
  — findings an earlier round over-rated; read before rating;
- threads already open: the brief's `open_threads` + any comment newer than the brief. A finding that
  duplicates one is dropped before it posts.

## 1. Semgrep first

`semgrep --config p/default --metrics off --quiet <touched paths, absolute>` (pinned ruleset:
semgrep's auto config refuses metrics off) (or `semgrep ci --sarif` where the repo is configured). Fold
the mechanical hits in so reasoning goes to the semantic class — concurrency, migration safety, money and
units, security. Absent or denied ⇒ say so under *Covered* and continue.

## 2. Lenses

- **`review.docs`** (repo-relative): each entry whose `applies_to` matches the diff, read at the head sha
  (`git show <sha>:<path>`), never the parked checkout. A finding it produces cites the doc's section.
- **Review runbooks** (workspace-side): every name in `runbooks` matching `review-*.md`, path from
  `registry.py runbook <key> <name>`; each states its own `applies_to`. Applied as lenses; a finding it
  produces states the mechanism and never cites the runbook (internal).
- Never copied into this skill.

## 3. Trace the data flow

Enumerate callers and consumers of every changed symbol; follow a changed value to where it lands
(display, persistence, export, solver input); judge at the point of impact — a hunk alone confirms nothing.
Dimensions: correctness, error handling (swallowed context, silent fallback), tests (discriminating — fails
on the pre-change code), types and invariants, comments, security.

**Comment volume is a finding in its own right.** Comments are checked for truth, not existence: a
multi-line narrative block, a restatement of the code, a rationale or safety argument that belongs in the PR
body — raised at the severity its cost warrants (a stale security claim is not cosmetic). Judged against the
`branching` minimal-comments rule.

## 4. Specialists — pr-review-toolkit via `Agent`

Fan out one `Agent` call per dimension, in parallel, in one message. Specialists are a hard dependency;
unavailable ⇒ say so under *Covered*, never imply the dimension ran.

| dimension | `subagent_type` | run when |
|---|---|---|
| correctness, quality, project-guideline fit | `pr-review-toolkit:code-reviewer` | always |
| silent failures, fallbacks, swallowed errors | `pr-review-toolkit:silent-failure-hunter` | always |
| test coverage and discrimination | `pr-review-toolkit:pr-test-analyzer` | the diff adds or changes logic or tests |
| comment truth and volume | `pr-review-toolkit:comment-analyzer` | the diff adds or touches comments |
| type encapsulation and invariants | `pr-review-toolkit:type-design-analyzer` | the diff adds or changes a type |
| simplification | `pr-review-toolkit:code-simplifier` | optional; its output is Low unless it names a behavioral gap |

Each prompt carries: repo slug, PR, head sha, the worktree's absolute path, `owned_paths`, the matching
lenses (paths + `applies_to`), the dimension's scope; "read-only — never edit, post, comment or write the
tracker; `samples/` is read-only reference, never the target"; return findings with repo-relative `path`,
head-side `line`, severity, what and why.

**Reconcile, then verify.** Drop a specialist hit that restates a Semgrep hit (keep the better-reasoned
one); merge duplicates across specialists. Every surviving candidate is an input, not a finding: re-read its
`path:line` at the head and trace it yourself before it counts. Unverifiable ⇒ the boundary tests decide
([findings.md](findings.md)) — a question at Medium, or dropped. Specialists' severities are re-mapped, never
copied (*Mapping a tool's rating*).

## 5. Scenario fit — against the brief's scenarios

- a scenario this PR claims and the diff does not satisfy ⇒ **High**, inline at the closest hunk;
- claimed by another rung, or unclear which PR delivers it ⇒ PM call, not posted;
- behavior in the diff no scenario asks for ⇒ **Medium** phrased as a question + a PM call. The behavior
  itself is the operator's to decide, never the reviewer's.

Scenario acceptance as a whole is not the reviewer's: it is `validate`'s, walked with the operator.

## 6. Validation

`packages[].validate` for touched packages only, never repo-wide; run from the worktree. Denied, or blocked
by the worktree (dependencies not installed) ⇒ "not run" under *Covered*, never implied green. Executed
evidence counts only at the layer it exercised ([findings.md](findings.md)).

## 7. PR text

- A story key other than the delivered one in the body, a comment or the review — as a key, URL or link —
  attaches and moves a story the PR does not deliver ⇒ Medium. Read the PR's issue comments for tracker
  link posts: more than one attached story is the same defect.
- Body claims the diff contradicts ⇒ finding at its consequence.
- Never restate the PR's own text as a finding.

## 8. Rate

Every candidate through [findings.md](findings.md) → tiers, boundary tests, drops. The rating step is where
over-publication is fixed, not the posting step.

## Verification mode

Another reviewer's substantive review exists: triage every posted finding as a claim against the current
head ([triage.md](triage.md) A–C: confirmed / narrower / refuted / stale / out of scope, `path:line`
evidence, re-rated), plus an independent sweep (steps 1–7). Only **new** Critical/High/Medium post; the
counts line counts the new ones only. Verdicts on others' threads follow SKILL.md → *Earlier rounds*.

## Deep mode

The brief says `deep: true` → [deep-review.md](deep-review.md) replaces step 4. Never self-selected.
