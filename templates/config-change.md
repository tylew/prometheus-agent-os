---
description: Configurator → seat. One proposed change to the prometheus plugin or registry; nothing is edited until the seat signs off.
---
# config-<slug>

**Problem** — what failed, for which role, with evidence (denial text, transcript path, failing check).

**Owner** — the file and rule that own this behaviour.

**Change** — the smallest edit that fixes it at the owner; copies removed.

**Behaviour change?** — no (mechanical) · yes: <what an agent will now decide or do differently>

**Tier** — 1 · 2 · 3 (highest that applies; all below run too)

**Acceptance criteria** — each a check that will run:
- [ ] <probe / test / lint / e2e step that fails today and passes after>
- [ ] suite + lint green

**Relaunch** — running tabs that must restart to pick it up.
