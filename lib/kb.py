#!/usr/bin/env python3
# ---
# name: kb
# description: The only write path into the knowledge base at docs/kb/. Indexes notes, resolves mentions to entities by slug/title/alias, searches by type/scope/edge, creates notes from templates, applies ingest proposals (final facts land; tentative, ambiguous and decisions held in ~/.claude/prometheus/kb-inbox/), checks schema and integrity, and migrates docs/vault/.
# usage: kb.py {index|resolve <mention>|search [filters]|new <type> <title>|apply <proposal.json> [--dry-run]|inbox [confirm|drop <id>]|check|migrate [--write]} [--json]
# ---
import sys

sys.exit("kb: not implemented")
