---
description: One behavior-spec story. Drafted by the planner in docs/specs/<project>/backlog/<slug>.md; the body below the frontmatter is posted verbatim as the Shortcut description. Frontmatter is local only.
title: <verb + an outcome a user can see — never sc-#####, no status words>
project: <registry key>
type: feature | bug | chore
epic: <epic id or name>
estimate: <1 | 2 | 3 | 5 | 8 — 8 means split>
requested_by: <operator | meeting ref | PM unit>
status: draft | confirmed | created
story: <sc-##### once created>
---

## What we're building and why

<Today's behavior → the gap → "This story …" saying what a user sees change. Business before mechanism.
 For a bug, the symptom leads.>

## What's decided

- **<the claim>** (<Name>, <YYYY-MM-DD>).

## Still open

- **<Name>:** <the ask>. Blocks this story.

## Scenarios

```gherkin
Feature: <the capability, as the title says it>
  As a <the role that benefits>
  I want <the capability>
  So that <the outcome they get>

  Scenario: <the main behavior>
    Given <precondition>
    When <the single user action>
    Then <what they can now observe>

  Scenario Outline: <the same behavior across inputs>
    Given a <subject> with <input>
    When <the user action>
    Then <what they observe, parameterised on <result>>

    Examples:
      | input   | result  |
      | <value> | <value> |

  Scenario: <the negative case — what does not happen>
    Given <the condition that makes it not apply>
    When <the same user action>
    Then <the absence someone can confirm>
    But <what still holds>
```

## Acceptance criteria

- [ ] <first scenario name, verbatim>
- [ ] <second scenario name, verbatim>
- [ ] <third scenario name, verbatim>

<!-- Rules (prometheus:stories): 150–200 words of prose, 300 ceiling; Scenarios outside the count, 3–5;
     Then = what a user can observe; no path, class, function, column, table, endpoint or flag key
     anywhere — a flag is named by what it gates; a flag-gated story owes a flag-off scenario;
     Background only when every scenario needs it; one checkbox per scenario, an Outline is one box;
     at most one <details>, titled with the question it answers. Engineering detail → design.md / plan.md. -->
