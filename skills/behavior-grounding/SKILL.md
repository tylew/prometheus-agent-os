---
name: behavior-grounding
description: "The project manager's behavior gate: trace every plan item to an operator-defined scenario, turn any gap or implied behavior into an operator question, and confirm every UI change (component, change, page, location) before it is built."
---

# behavior-grounding

The lead's behavior gate. Behavior comes from the operator; nobody invents it.

## Trace

- Every plan work item names the operator scenario it serves (the unit's Gherkin, verbatim from the story).
- An item serving none is cut, or raised to the operator as a question.
- A gap, an ambiguity, or behavior implied but not stated → one question per fork to the operator, built
  behavior named, options as choices. It enters the plan only once answered.
- A change to a story's scenarios goes back to the `planner` and the operator — never edited by the PM.

## UI changes — confirmed before build

One card per change (`templates/ui-change.md`):

- **Component** — as a user would name it
- **Change** — added · modified · removed · updated, and what changes
- **Page** — the page or route
- **Location** — where on the page, in general terms

Build waits on the operator's confirmation. The confirmed cards go into the implementor's brief; the
implementor changes nothing visible beyond them.

## Asking

Operator typing in your tab (untagged input) → ask in place. Otherwise `send.sh --role seat` and end the turn.
