---
description: Start the Prometheus delivery OS from the seat — verify Herdr, start the dispatcher tab if none is running, report what it watches.
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/skills/dispatch/scripts/begin.sh), Bash(herdr workspace list*)
---

Run `${CLAUDE_PLUGIN_ROOT}/skills/dispatch/scripts/begin.sh` and report its last line.

Then report, one line each: the dispatcher's status, and every live unit workspace (`herdr workspace list`,
those carrying a prometheus `unit` token) with its kind and stage. If begin.sh fails, report its error and
stop — never start a dispatcher any other way.
