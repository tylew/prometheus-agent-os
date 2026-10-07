---
name: data
description: "Reading operational data for a quick work item or an investigation: Redash saved queries through redash.sh (read-only, CSV out), and the MCP servers a role is given (Datadog, LaunchDarkly, Buildkite, Shortcut — see templates/mcp/roles.json). Use when an ask needs numbers, rows or production state rather than code."
---

# data

**Redash** — `redash.sh` (on PATH), read-only: saved queries only, no ad-hoc SQL, no edits.

```
redash.sh queries --search "<words>"                       id · name · data source
redash.sh query <id>                                        its SQL and parameters
redash.sh run <id> --out <exports>/<name>.csv [--param k=v]... [--max-age 0]
```
No saved query fits → say so and propose the SQL to the operator; never create one. Report the CSV path, row
count and `retrieved_at`.

**MCP** — each role gets a fixed set (`templates/mcp/roles.json`); write tools are denied except to their
writers, and a LaunchDarkly change by a PM is a per-call prompt the operator answers. A server that needs
authentication → report it; never work around it.

Setup (operator, once): `tools.redash_url` in `.claude/prometheus/local.json`; the key in the keychain —
`security add-generic-password -s prometheus-redash -a redash -w <key>`.
