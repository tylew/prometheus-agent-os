# Worked example — a filled-in story body

Read for register and scenario grain; draft from `templates/story.md`, never copy this. Shortcut stores
and renders a fenced `gherkin` block, pipe tables included, and ticking a box leaves the block intact.
Budget: 95 prose words + 3 scenarios outside the count.

---

## What we're building and why

An invoice downloads only as a spreadsheet today, so a customer who wants to see what their plan saved
them has to work it out from the line items. This story adds a PDF download that shows the plan discount
as its own line.

## What's decided

- **PDF only, not Word** (Reuben, 2026-10-05). Word would need a second renderer and nobody has asked
  for it.
- **Ships dark behind a release flag** (Reuben, 2026-10-05). With the flag off the export menu is
  exactly what it is today.

## Still open

Nothing.

## Scenarios

```gherkin
Feature: Plan discount on the invoice PDF
  As a billing admin
  I want the plan discount shown on the invoice PDF
  So that a customer can see what their plan saved them

  Scenario Outline: A discounted plan shows its discount
    Given a customer on the <plan> plan
    And the invoice PDF release flag is on
    When they download an invoice
    Then the invoice PDF shows "Plan discount" as its own line, at <discount> of the subtotal

    Examples:
      | plan     | discount |
      | annual   | 10%      |
      | two-year | 15%      |

  Scenario: Monthly plan shows no discount line
    Given a customer on the monthly plan with a $100.00 subtotal
    And the invoice PDF release flag is on
    When they download an invoice
    Then the invoice PDF has no "Plan discount" line
    But the total still reads $100.00

  Scenario: Flag off changes nothing
    Given the invoice PDF release flag is off
    When a customer on any plan opens the export menu
    Then the menu offers exactly the formats it offered before this story
```

## Acceptance criteria

- [ ] A discounted plan shows its discount
- [ ] Monthly plan shows no discount line
- [ ] Flag off changes nothing

---

Why it reads this way:

- The Outline carries two plans in one scenario; two Scenarios would say it twice and cost two boxes.
- "Then the invoice PDF shows a Plan discount line" is observable; "Then the PDF service writes a
  discount row" names a mechanism → `design.md`.
- The flag is named by what it gates, never by its key; the flag-off scenario checks the claim most
  likely to be wrong and never checked.
- Three scenarios, three boxes, names copied verbatim.
