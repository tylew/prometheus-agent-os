# Triage — a finding is a claim, not a verdict

Every finding — a human's, a bot's, a specialist's, this loop's — is a claim about the code, unchecked.
Callers: the reviewer in **verification mode** and on **earlier rounds** (A–C), and the **PM on the
operator's own PR** ([addressing-review.md](addressing-review.md) step 2: A–D, then the PM's *Review
findings* defaults in `agents/project-manager.md`). **Triage the whole set before fixing anything** —
findings interact (one cause behind three; a refuted Critical removes two others).

## A. Restate the claim, separately from the remedy

Per comment: the **claim** — a falsifiable assertion about the code ("`x` is undefined when the query
errors, so the gate renders eligible") — then the **remedy** proposed, if any. They fail independently;
triage the claim, weigh the remedy at D. No falsifiable claim (a question, a preference, a "consider…") ⇒
not a finding: answer on the thread, no worklist entry.

## B. Verify the claim against the code

Read the cited `path:line` at the PR's **current head**, trace the data flow, run the test if a test
settles it. Never verify against the reviewer's summary.

| verdict | means |
|---|---|
| **Confirmed** | holds as stated |
| **Narrower** | real, but smaller or differently caused — wrong severity, wrong mechanism, one of three cited sites |
| **Refuted** | false at this head — a guard upstream, context the reviewer lacked, an API that doesn't behave as claimed |
| **Stale** | was true; fixed by a later commit on this PR |
| **Out of scope** | true, but pre-existing and untouched by this diff |

Severity is re-rated here on the five tiers through the boundary tests ([findings.md](findings.md)); a
reviewer's tier is an input. Authority is not evidence. Red flags before accepting any finding:

- behavior claimed in a file the diff does not touch;
- the cited `path:line` does not hold the code described;
- a "risk" that restates what the diff does without naming an input that fails;
- a pattern the repo chose deliberately (read the precedent first);
- a remedy written against a signature that does not exist.

## C. Disposition — does it warrant a change on this PR?

| verification | disposition |
|---|---|
| Confirmed, Critical/High | fix on this PR |
| Confirmed, Medium | fix if cheap and in a file the diff already touches; otherwise decline with the reason |
| Confirmed, Low | never posted by this loop; received from elsewhere, fix only if free |
| Narrower | fix the real defect, not the described one — the reply states the delta |
| Refuted | decline; the reply carries the evidence |
| Stale | no change; the reply names the commit that fixed it |
| Out of scope | decline for this PR; worth keeping ⇒ a proposed story to the planner (`send.sh --role planner`) |

Scope growth at any tier is the operator's call, never declined on the PM's own (`agents/project-manager.md`
→ *Review findings*). Every disposition ends in reply + resolve, declines included; a decline reply carries
evidence, not opinion. An unresolved thread is not a defect — fixing to clear one is the failure mode.

**Calibration memo.** A received finding that did not help or was over-rated — restates a documented,
chosen tradeoff with no failing input, proposes net-new UI as the remedy, lands a tier above the scale —
gets one short entry in `<state_dir>/reviews/calibration.md`: PR,
the finding's title and tier, why it missed. Written at triage by the PM; every reviewer reads it before
rating ([review-pass.md](review-pass.md) step 0).

**Verification mode and a follow-up round end here.** Only *new* Critical/High/Medium post; existing
findings already have threads, and nothing is published twice.

## D. Shape the fix (author side only)

| shape | means | what it takes |
|---|---|---|
| **Local** | the design holds; bounded to files the diff already touches | the change + touched-package validation (`packages[].validate`) |
| **Test-only** | the code is right, the coverage isn't | a *discriminating* test — fails against the pre-fix code; a test that passes either way is not coverage |
| **Cross-cutting** | correct here, and the same defect exists at other call sites | fix every site in this PR, or here plus a proposed story for the rest — say which on the thread |
| **Design-affecting** | changes the approach, a contract/interface, scope, or a recorded decision | PM / operator first ([addressing-review.md](addressing-review.md) step 3) — never silently patched into code |

Unclear between Local and Design-affecting ⇒ Design-affecting: a recorded delta is cheap, a silently
changed design is not.
