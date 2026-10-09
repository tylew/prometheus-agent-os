#!/usr/bin/env python3
# ---
# name: tracker
# description: The engine's one Shortcut interface — read a story (state, labels, owners, description) and the writes the engine makes after Ready (owner add, label add / remove, state move, comment), each verified by a read-back. Backend: the REST API when a personal token (SHORTCUT_API_TOKEN) verifies against /member; otherwise a claude -p call over the Shortcut MCP limited to the one tool the write needs, then the same read-back. A write whose read-back disagrees raises.
# usage: tracker.py backend | tracker.py get <sc-id> [--json]
# ---
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

API = "https://api.app.shortcut.com/api/v3"
STORY_SCHEMA = {"type": "object", "required": ["id", "state", "labels", "owner_ids", "description"],
                "properties": {"id": {"type": "string"}, "state": {"type": "string"},
                               "labels": {"type": "array", "items": {"type": "string"}},
                               "owner_ids": {"type": "array", "items": {"type": "string"}},
                               "description": {"type": "string"}}}
DONE_SCHEMA = {"type": "object", "required": ["done"], "properties": {"done": {"type": "boolean"},
                                                                      "error": {"type": "string"}}}


class TrackerError(RuntimeError):
    pass


def _num(sid: str) -> str:
    return sid.split("-", 1)[1] if sid.startswith("sc-") else sid


class Rest:
    name = "rest"

    def __init__(self, token: str):
        self.token = token
        self._states: dict | None = None

    def call(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None,
                                     headers={"Shortcut-Token": self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise TrackerError("Shortcut %s %s → %s" % (method, path, exc.code)) from exc
        return json.loads(raw) if raw else None

    def verify(self) -> bool:
        try:
            return bool(self.call("GET", "/member"))
        except (TrackerError, urllib.error.URLError, OSError):
            return False

    def states(self) -> dict:
        if self._states is None:
            self._states = {s["name"]: s["id"] for w in self.call("GET", "/workflows") for s in w["states"]}
        return self._states

    def get(self, sid: str) -> dict:
        s = self.call("GET", "/stories/%s" % _num(sid))
        names = {v: k for k, v in self.states().items()}
        return {"id": "sc-%s" % s["id"], "state": names.get(s["workflow_state_id"], str(s["workflow_state_id"])),
                "labels": [l["name"] for l in s.get("labels", [])], "owner_ids": list(s.get("owner_ids", [])),
                "description": s.get("description", "")}

    def update(self, sid: str, cur: dict, **change) -> None:
        body = {}
        if "labels" in change:
            body["labels"] = [{"name": n} for n in change["labels"]]
        if "owner_ids" in change:
            body["owner_ids"] = change["owner_ids"]
        if "state" in change:
            body["workflow_state_id"] = self.states()[change["state"]]
        self.call("PUT", "/stories/%s" % _num(sid), body)

    def comment(self, sid: str, text: str) -> None:
        self.call("POST", "/stories/%s/comments" % _num(sid), {"text": text})


class Mcp:
    name = "mcp"
    URL = os.environ.get("SHORTCUT_MCP_URL", "https://mcp.shortcut.com/mcp")

    def _ask(self, prompt: str, schema: dict, tools: list[str]):
        import events
        return events.claude_json(prompt, schema, mcp={"shortcut": {"type": "http", "url": self.URL}},
                                  allowed=["mcp__shortcut__%s" % t for t in tools], budget=0.10)

    def get(self, sid: str) -> dict:
        return self._ask("Read-only. Call stories-get-by-id once for story %s. Return its id as sc-<number>, the "
                         "workflow state's name, label names, owner ids and the description verbatim."
                         % _num(sid), STORY_SCHEMA, ["stories-get-by-id"])

    def update(self, sid: str, cur: dict, **change) -> None:
        what = []
        if "labels" in change:
            what.append("set the labels to exactly %s" % json.dumps(change["labels"]))
        if "owner_ids" in change:
            what.append("set the owner ids to exactly %s" % json.dumps(change["owner_ids"]))
        if "state" in change:
            what.append("move it to the workflow state named %r" % change["state"])
        out = self._ask("Call stories-update once on story %s and change nothing else: %s. Return done=true "
                        "only if the call succeeded." % (_num(sid), "; ".join(what)), DONE_SCHEMA,
                        ["stories-update", "stories-get-by-id"])
        if not out.get("done"):
            raise TrackerError("MCP update on %s failed: %s" % (sid, out.get("error", "?")))

    def comment(self, sid: str, text: str) -> None:
        out = self._ask("Call stories-create-comment once on story %s with exactly this text, verbatim:\n\n%s\n\n"
                        "Return done=true only if the call succeeded." % (_num(sid), text), DONE_SCHEMA,
                        ["stories-create-comment"])
        if not out.get("done"):
            raise TrackerError("MCP comment on %s failed: %s" % (sid, out.get("error", "?")))


_backend = None


def backend():
    global _backend
    if _backend is None:
        token = os.environ.get("SHORTCUT_API_TOKEN")
        rest = Rest(token) if token else None
        _backend = rest if rest and rest.verify() else Mcp()
    return _backend


class Tracker:
    """Every write is followed by a read; the read must show the change, else TrackerError."""

    def __init__(self, be=None):
        self.be = be or backend()

    def get(self, sid: str) -> dict:
        return self.be.get(sid)

    def _write(self, sid: str, check, **change) -> dict:
        cur = self.be.get(sid)
        if check(cur):
            return cur
        self.be.update(sid, cur, **change)
        after = self.be.get(sid)
        if not check(after):
            raise TrackerError("%s: write not visible on read-back (%s)" % (sid, ", ".join(change)))
        return after

    def add_owner(self, sid: str, member: str) -> dict:
        cur = self.be.get(sid)
        return self._write(sid, lambda s: member in s["owner_ids"], owner_ids=cur["owner_ids"] + [member])

    def add_label(self, sid: str, name: str) -> dict:
        cur = self.be.get(sid)
        return self._write(sid, lambda s: name in s["labels"], labels=cur["labels"] + [name])

    def remove_label(self, sid: str, name: str) -> dict:
        cur = self.be.get(sid)
        return self._write(sid, lambda s: name not in s["labels"], labels=[l for l in cur["labels"] if l != name])

    def set_state(self, sid: str, state: str) -> dict:
        return self._write(sid, lambda s: s["state"] == state, state=state)

    def comment(self, sid: str, text: str, marker: str) -> None:
        """`marker` (an HTML comment the text carries) makes a repeated call a no-op: the engine checks the
        story's comments for it before posting — callers pass the same marker for the same intent."""
        if marker not in text:
            raise TrackerError("comment text must carry its marker")
        self.be.comment(sid, text)


def main(argv: list[str]) -> int:
    if argv[:1] == ["backend"]:
        print(backend().name)
        return 0
    if len(argv) >= 2 and argv[0] == "get":
        print(json.dumps(Tracker().get(argv[1]), indent=None if "--json" in argv else 2))
        return 0
    print("usage: tracker.py backend | tracker.py get <sc-id> [--json]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
