---
name: dispatch
description: "The dispatcher: a lock-guarded script loop in the control workspace that polls GitHub (review requested, authored PRs) and Shortcut (claude -p over MCP), matches each event to a unit workspace by story id or PR stack, routes matched events to the unit's PM, triages unmatched ones with a one-shot claude -p, auto-creates review units, sends other proposals to the seat, resumes dead PMs, and settles bound KB decisions when a story reaches Completed or Won't Fix (kb.py inbox settle --story)."
---

# dispatch

Not implemented — phase 2.
