# Self-review — before requesting a human

The operator's own PR is not exempt from the review discipline. The PM runs it before requesting a human
reviewer (un-draft or `--reviewers`), after the implementor's validation is green.

1. Brief a fresh `review-<pr>` reviewer session exactly as a round ([review-loop.md](review-loop.md) →
   *Round 1*), `requested: yes`. The event is `COMMENT` — GitHub refuses an approve or a change request
   from the PR's own author; the gate still decides the disposition the counts line states
   ([findings.md](findings.md)).
2. The project's review runbooks apply in full — self-review goes blind exactly on the project-specific
   traps the toolkit cannot know. Probe adversarially (what breaks if the new dependency is missing, under a
   query failure, are the tests discriminating); never narrate the change.
3. Structured counts, never "LGTM": `0 critical · 0 high · 0 medium`, a brief summary, what was checked.
   Low and Note stay off the PR here too — a self-review is where the nit pile grows fastest.
4. Deep mode only on the operator's opt-in ([deep-review.md](deep-review.md)).
5. Findings go to the implementor as fixes (triage first — [triage.md](triage.md)); request the human only
   once the self-review closes "clean at this head".
6. **Author inline notes** *(home)* — before requesting review, the PM posts review comments on its own
   diff at the hunks a reviewer would stop at (non-obvious choice, deliberate trade-off, where to start
   reading): one `COMMENT` review, inline only, objective voice, no internal-doc names. Not code comments;
   the body's *Notes for reviewer* keeps the summary.
