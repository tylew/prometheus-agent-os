#!/usr/bin/env python3
# ---
# name: herdr
# description: Herdr access for every prometheus script — the CLI (JSON result, typed errors with Herdr's code), pane reads, agent start / prompt-and-wait, and an events.subscribe client that wakes a waiter on any pane / workspace change (reconnects with backoff; falls back to polling). Event payloads are only a "something changed" signal; state is always re-read.
# usage: imported (import herdr)
# ---
# Event client and error handling follow Horchestra's herdr_client.py
# (https://github.com/SimoneDaniotti/horchestra), MIT License, Copyright (c) 2026 Simone Daniotti.
from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time

SOURCE = "prometheus"
EVENTS = ["pane.created", "pane.closed", "pane.updated", "pane.exited", "pane.agent_detected",
          "workspace.closed", "tab.closed"]


class HerdrError(RuntimeError):
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


def bin_path() -> str:
    return os.environ.get("HERDR_BIN") or os.environ.get("HERDR_BIN_PATH") or "herdr"


def _error_doc(text: str) -> dict | None:
    for line in reversed(text.strip().splitlines()):
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict) and isinstance(doc.get("error"), dict):
            return doc["error"]
    return None


def call(*args: str, timeout: float = 30) -> dict:
    """Run `herdr <args>`; its JSON `result`, or HerdrError carrying Herdr's error code."""
    try:
        out = subprocess.run([bin_path(), *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise HerdrError("herdr %s: timed out" % " ".join(args[:3]), code="timeout") from exc
    if out.returncode != 0:
        err = _error_doc(out.stdout) or _error_doc(out.stderr) or {}
        msg = err.get("message") or out.stderr.strip() or "exit %d" % out.returncode
        raise HerdrError("herdr %s: %s" % (" ".join(args[:3]), msg), code=err.get("code"))
    try:
        doc = json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() else {}
    except ValueError:
        return {}
    if isinstance(doc.get("error"), dict):
        raise HerdrError("herdr %s: %s" % (" ".join(args[:3]), doc["error"].get("message", "")),
                         code=doc["error"].get("code"))
    return doc.get("result") or {}


def snapshot() -> dict:
    return call("api", "snapshot").get("snapshot", {})


def read(pane_id: str) -> str:
    out = subprocess.run([bin_path(), "pane", "read", pane_id], capture_output=True, text=True, timeout=30)
    return out.stdout if out.returncode == 0 else ""


def start_agent(name: str, pane_id: str, args: list[str], timeout_ms: int = 90000) -> dict:
    """Start Claude in a shell pane; returns once Herdr sees it ready for input."""
    return call("agent", "start", name, "--kind", "claude", "--pane", pane_id,
                "--timeout", str(timeout_ms), "--", *args, timeout=timeout_ms / 1000 + 15)


def prompt_wait(pane_id: str, text: str, attempts: int = 3) -> str:
    """Submit a prompt and confirm a turn started. A just-started TUI can drop the text; Herdr then
    reports agent_prompt_stalled and the prompt is sent again. Returns started | queued | stalled."""
    for _ in range(attempts):
        try:
            call("agent", "prompt", pane_id, text, "--wait", "--until", "working", "--timeout", "15000",
                 timeout=45)
            return "started"
        except HerdrError as exc:
            if exc.code == "timeout":
                return "queued"
            if exc.code != "agent_prompt_stalled":
                raise
            time.sleep(3)
    return "stalled"


class Watcher(threading.Thread):
    """Holds an events.subscribe stream; `changed` is set on any event and after every reconnect.
    Agent status changes need one subscription per pane: `watch(pane_ids)` resubscribes when the set
    changes."""

    def __init__(self, events: list[str] | None = None):
        super().__init__(daemon=True)
        self.changed = threading.Event()
        self.connected = False
        self._events = list(events or EVENTS)
        self._panes: frozenset = frozenset()
        self._per_pane = True
        self._dirty = threading.Event()
        self._lock = threading.Lock()

    def watch(self, pane_ids) -> None:
        ids = frozenset(pane_ids)
        with self._lock:
            if ids != self._panes:
                self._panes = ids
                self._dirty.set()

    def _subscriptions(self) -> list[dict]:
        subs = [{"type": t} for t in self._events]
        if self._per_pane:
            with self._lock:
                subs += [{"type": "pane.agent_status_changed", "pane_id": p} for p in sorted(self._panes)]
        return subs

    def run(self) -> None:
        path = os.environ.get("HERDR_SOCKET_PATH")
        if not path or not hasattr(socket, "AF_UNIX"):
            return
        backoff = 1.0
        while self._events:
            try:
                self._stream(path)
                backoff = 1.0
            except (OSError, ValueError):
                pass
            self.connected = False
            self.changed.set()
            time.sleep(backoff)
            backoff = min(backoff * 2, 10.0)

    def _stream(self, path: str) -> None:
        self._dirty.clear()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        try:
            sock.connect(path)
            req = {"id": "prometheus", "method": "events.subscribe",
                   "params": {"subscriptions": self._subscriptions()}}
            sock.sendall((json.dumps(req) + "\n").encode())
            buf, acked = b"", False
            while not self._dirty.is_set():
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    return
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not acked:
                        acked = True
                        if "error" in json.loads(line):
                            # rejected: drop per-pane, then the minimal set, then give up to polling
                            if self._per_pane:
                                self._per_pane = False
                            else:
                                self._events = [] if len(self._events) <= 3 else self._events[:3]
                            return
                        self.connected = True
                        continue
                    self.changed.set()
        finally:
            sock.close()

    def wait(self, timeout: float) -> bool:
        hit = self.changed.wait(timeout)
        self.changed.clear()
        return hit
