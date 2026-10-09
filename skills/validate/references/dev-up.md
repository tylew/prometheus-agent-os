# dev-up — local dev, discipline only

Mechanics (pieces, ports, commands, probes, base path, known-noisy endpoints, traps) live in the project
runbook:

```
python3 <plugin>/lib/registry.py runbook <project> dev-up.md
```

Read it first. No runbook → no guessed bring-up: say so, offer to write one from the repo's
compose / Makefile / package scripts.

## Rules

1. **Base checkout only** — `registry.py field repo.root --key <project>`, never a worktree. The browser
   and the watcher point there; worktree builds miss the canonical path and serve stale code. To serve a
   worktree's branch: `git -C <wt> switch --detach`, then check the branch out in the base checkout
   (`branching`).
2. **Check before starting.** Ports and containers first: all healthy → start nothing; partial → take the
   affected pieces down, then up; none → start all. A second server grabs another port silently.
3. **Detach long-running processes**: `nohup <cmd> > <logfile> 2>&1 & disown`, never a harness background
   task (a reaped task kills its process group). Watch the log for the ready / error line.
4. **Migrate every bring-up** when the project has a schema; a behind DB reads as a runtime 500.
5. **Probe for real**: app and one API endpoint, real status codes. A listening port is not a service.
   Runbook-listed noisy endpoints are not breakage; a local error may be a missing route — check the route
   table before diagnosing a handler.
6. **Prove the served tree** at bring-up and again before recording any verdict: `git log -1` and
   `git reflog` on the base checkout, then probe the served artifact for a symbol the branch **adds** and
   one it **removes** (present-only passes against a stale build). Behavior is attributed to code only when
   that code is proven served; when the rendered output is the evidence, corroborate with an access-log
   line (real browser request, 2xx, timestamp inside the proven window).

## Down

Stop the pieces the runbook lists by their pid / container; confirm the ports are free.

## Writing back

A new trap → the project runbook, same session.
