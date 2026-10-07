#!/usr/bin/env python3
# ---
# name: redash
# description: Read-only Redash over its REST API — find saved queries, show one (parameters, data source), run a saved query with parameters and write its rows to a CSV. No ad-hoc SQL, no query edits. URL from local.json tools.redash_url (or PROMETHEUS_REDASH_URL); API key from the macOS keychain (service prometheus-redash) or PROMETHEUS_REDASH_KEY — never from a committed file.
# usage: redash.py {queries [--search T] | query <id> | run <id> --out <file.csv> [--param k=v]... [--max-age S]}
# ---
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
KEYCHAIN_SERVICE = "prometheus-redash"


def config() -> tuple[str, str]:
    url = os.environ.get("PROMETHEUS_REDASH_URL")
    if not url:
        try:
            import registry
            url = (registry.local_config().get("tools") or {}).get("redash_url")
        except Exception:  # noqa: BLE001 — a missing registry just means no configured URL
            url = None
    key = os.environ.get("PROMETHEUS_REDASH_KEY")
    if not key:
        out = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                             capture_output=True, text=True)
        key = out.stdout.strip() if out.returncode == 0 else ""
    if not url or not key:
        raise SystemExit("redash: not configured — set tools.redash_url in .claude/prometheus/local.json and store the "
                         "API key: security add-generic-password -s %s -a redash -w <key>" % KEYCHAIN_SERVICE)
    return url.rstrip("/"), key


def call(method: str, path: str, body: dict | None = None):
    url, key = config()
    req = urllib.request.Request(url + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Key " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        raise SystemExit("redash: %s %s → %s %s" % (method, path, exc.code, exc.read()[:300].decode(errors="replace")))


def run(query_id: int, params: dict, max_age: int, timeout: float = 600) -> dict:
    res = call("POST", "/api/queries/%d/results" % query_id, {"parameters": params, "max_age": max_age})
    deadline = time.time() + timeout
    while "job" in res:
        job = res["job"]
        if job.get("status") == 3:
            return call("GET", "/api/query_results/%s" % job["query_result_id"])["query_result"]
        if job.get("status") in (4, 5):
            raise SystemExit("redash: query %d failed: %s" % (query_id, job.get("error")))
        if time.time() > deadline:
            raise SystemExit("redash: query %d still running after %ds" % (query_id, timeout))
        time.sleep(1.5)
        res = call("GET", "/api/jobs/%s" % job["id"])
    return res["query_result"]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="redash.sh")
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("queries")
    q.add_argument("--search", default="")
    sub.add_parser("query").add_argument("id", type=int)
    r = sub.add_parser("run")
    r.add_argument("id", type=int)
    r.add_argument("--out", required=True, help="CSV file to write (e.g. in your exports folder)")
    r.add_argument("--param", action="append", default=[], help="k=v; repeatable")
    r.add_argument("--max-age", type=int, default=0, help="seconds a cached result may be old (0 = run fresh)")
    a = ap.parse_args(argv)
    if a.cmd == "queries":
        rows = call("GET", "/api/queries?page_size=50&q=%s" % urllib.request.quote(a.search))["results"]
        for x in rows:
            print("%s\t%s\t%s" % (x["id"], x["name"], x.get("data_source_id")))
    elif a.cmd == "query":
        x = call("GET", "/api/queries/%d" % a.id)
        print(json.dumps({"id": x["id"], "name": x["name"], "data_source_id": x.get("data_source_id"),
                          "parameters": (x.get("options") or {}).get("parameters", []),
                          "query": x.get("query")}, indent=1))
    else:
        params = dict(p.split("=", 1) for p in a.param)
        result = run(a.id, params, a.max_age)
        cols = [c["name"] for c in result["data"]["columns"]]
        rows = result["data"]["rows"]
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print("redash: query %d → %s (%d rows, %d columns, retrieved %s)"
              % (a.id, os.path.abspath(a.out), len(rows), len(cols), result.get("retrieved_at")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
