---
description: Dispatcher → PM (or seat). The one line delivered per tick; details go in the file it names, so a noisy tick cannot flood the PM's context.
---

[prometheus] <unit> — <n> event(s): <kind> <subject> <change> · <kind> <subject> <change> · … — details: <path>

<!-- kinds: ci (pass|fail on <pr>) · review (<state> on <pr>) · comment (<pr|story>) · pr (merged|closed <pr>) ·
     story (<old> → <new> <sc-id>) · agent (<label> <old> → <new>) · heartbeat (no movement on <subject> for <n> min)
     details file: <state_dir>/events/<unit>/<tick>.json — one object per event with its source payload -->
