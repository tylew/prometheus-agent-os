#!/usr/bin/env python3
# ---
# name: registry
# description: The one resolver over .claude/prometheus/ (workspace.json, projects/<key>.json, local.json) plus the live layer (Herdr workspace/pane tokens, Claude sessions). active() = which product (override → unit token → pin → cwd → None); repo() = which checkout a git command mutates; check validates against registry.schema.json.
# usage: registry.py {active|repo --cwd <dir>|entry --key <key>|field <name> --key <key>|owner <path>|tracker <key>|runbook <key> <name>|unit|check} [--json]
# ---
import sys

sys.exit("registry: not implemented")
