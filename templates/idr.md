---
description: The story's Implementation Decision Record — written by the implementor before any product code at <state_dir>/engine/stories/<sc-id>/idr.md (units.story_dir), checked with `python3 <plugin>/lib/idr.py check <file>`, carried collapsed on the stack's bottom PR, landed in the team planning vault by vantage /session-closeout at Completed. Shape and budget are voltus-kanban rules/idr.md. Delete this frontmatter; the file starts at the title.
---

# IDR: <what the story delivers, in the story's words>

**Story:** [sc-#####](https://app.shortcut.com/<org>/story/#####)

## Approach

<Three to six sentences: where the new behavior sits, what calls what, what stays as it is. A **Split.**
line when backend and frontend both change: what each side carries and which lands first.>

```mermaid
flowchart LR
  A[<entry>] --> B[<where it changes>] --> C[<what persists or renders>]
```

```text
<optional pseudocode, at most 25 lines — never real code>
```

## Decisions

1. **<the claim>** Why: <the reason>. Instead of: <the alternative it beat, and what that would have cost>.

## Where the scenarios are tested

<The seam in words: the outermost level the package's own tests already run, and the framework. One per
side when the story has two. Any scenario no seam can observe, and what would prove it.>

## Rollout and observability

**Observability.** <what is logged or monitored, or why nothing new>
**Rollout.** <flag targeting and the rollout ladder, or why none>
**Rollback.** <how it is undone>

<!-- Budget (idr.py check): ≤400 words outside fenced blocks, 600 the hard stop; ≤2 Mermaid diagrams;
     ≤25 pseudocode lines; ≤6 decisions. Never: real code, file:line, a task list, anything the story
     already says, a Scenario: line, a question or TBD, wikilinks, decision ids. Over budget after one
     honest trim ⇒ Stop (needs a spike). Modules and functions in backticks; a package or component by
     its name. -->
