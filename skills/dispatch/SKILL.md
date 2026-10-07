---
name: dispatch
description: "The dispatcher — the only watcher; no agent polls, Monitors or loops. A lock-guarded script loop in the control workspace that polls GitHub (review requested, authored PRs), Shortcut (claude -p over MCP) and every agent pane's state (herdr api snapshot), matches each event to a unit workspace by story id or PR stack, routes matched events to the unit's pm pane by its tokens (delivered only in a safe state, coalesced per tick, heartbeat on stalls), triages unmatched ones with a one-shot claude -p, auto-creates review units, sends other proposals to the seat, resumes dead PMs, and settles bound KB decisions when a story reaches Completed or Won't Fix (kb.py inbox settle --story)."
---

# dispatch

Not implemented — phase 2.
