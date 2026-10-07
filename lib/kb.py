#!/usr/bin/env python3
# ---
# name: kb
# description: The only write path into the knowledge base at docs/kb/. Indexes notes, resolves mentions to entities by slug/title/alias/handle, searches by type/scope/edge, creates notes, applies ingest proposals under a lock (idempotent per proposal; final facts land; tentative facts, unquoted `stated` facts, ambiguous mentions, new people/orgs, contradicted fields and every decision are held in ~/.claude/prometheus/kb-inbox/), confirms/drops/settles held items, checks schema and integrity, and migrates docs/vault/.
# usage: kb.py {index|resolve <mention> [--type T]|search [--type T] [--scope S] [--text Q] [--edge E] [--links-to SLUG] [--orphans]|new <type> <title> [--scope S]|apply <proposal.json> [--dry-run]|inbox [list|confirm <id> [--as SLUG]|drop <id>|settle --story <sc-id> --state <Completed|Won't Fix>]|check|migrate [--write]} [--json]
# ---
from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import fcntl
import hashlib
import json
import os
import re
import sys

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import env  # noqa: E402
import schema_lite  # noqa: E402

KB_REL = os.path.join("docs", "kb")
VAULT_REL = os.path.join("docs", "vault")
SCHEMA_PATH = os.path.join(LIB, "kb.schema.json")
TYPES = ("person", "org", "concept", "system", "topic", "decision")
FINAL = ("decided", "merged", "stated", "confirmed")
EDGES = ("member_of", "owns", "works_with", "part_of", "depends_on", "evidence", "decided_by",
         "supersedes", "relates_to")
PERSON_FIELDS = ("role", "team", "reports_to", "location")
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")


def today() -> str:
    return os.environ.get("PROMETHEUS_TODAY") or _dt.date.today().isoformat()


def state_dir() -> str:
    d = os.environ.get("PROMETHEUS_STATE_DIR") or os.path.expanduser("~/.claude/prometheus")
    os.makedirs(d, exist_ok=True)
    return d


def kb_root(workspace: str | None = None) -> str:
    return os.path.join(workspace or env.workspace_root() or ".", KB_REL)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80] or "note"


def link(slug: str) -> str:
    return "[[%s]]" % slug


@contextlib.contextmanager
def kb_lock():
    with open(os.path.join(state_dir(), "kb.lock"), "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


# ------------------------------------------------------------- frontmatter

def _value(raw: str):
    raw = raw.strip()
    if raw == "":
        return ""
    try:
        return json.loads(raw)
    except ValueError:
        pass
    if raw.startswith("[") and raw.endswith("]"):
        return [v.strip().strip("\"'") for v in raw[1:-1].split(",") if v.strip()]
    if (raw[0] == raw[-1]) and raw[0] in "\"'":
        return raw[1:-1]
    return raw


def parse(text: str) -> tuple[dict, str]:
    m = re.match(r"---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        km = re.match(r"([A-Za-z_][A-Za-z0-9_]*):\s?(.*)$", line)
        if km:
            meta[km.group(1)] = _value(km.group(2))
    return meta, text[m.end():]


ORDER = ("title", "type", "part", "person", "scope", "status", "aliases", "role", "team", "reports_to",
         "location", "handles", "kind", "repo", "paths", "decided", "binds_to", "refs", "edges", "tags",
         "migrated_from", "created", "updated")


def dump(meta: dict, body: str) -> str:
    keys = [k for k in ORDER if k in meta] + sorted(k for k in meta if k not in ORDER)
    lines = ["%s: %s" % (k, json.dumps(meta[k], ensure_ascii=False)) for k in keys]
    return "---\n%s\n---\n\n%s" % ("\n".join(lines), body.lstrip("\n"))


# ---------------------------------------------------------------- notes

def note_path(root: str, typ: str, slug: str) -> str:
    if typ == "person":
        return os.path.join(root, "person", slug, "%s.md" % slug)
    return os.path.join(root, typ, "%s.md" % slug)


def interactions_path(root: str, slug: str) -> str:
    return os.path.join(root, "person", slug, "%s-interactions.md" % slug)


def walk(root: str):
    for dirpath, _dirs, files in os.walk(root):
        for f in sorted(files):
            if f.endswith(".md"):
                path = os.path.join(dirpath, f)
                with open(path) as fh:
                    meta, body = parse(fh.read())
                yield path, f[:-3], meta, body


def write_note(path: str, meta: dict, body: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as fh:
        fh.write(dump(meta, body))
    os.replace(path + ".tmp", path)


def index(root: str) -> dict:
    """slug → {type, path, title, aliases, handles, scope, edges, status}. Rebuilt from disk each call."""
    out = {}
    for path, slug, meta, _body in walk(root):
        if meta.get("type") not in TYPES:
            continue
        out[slug] = {"type": meta["type"], "path": path, "title": meta.get("title", slug),
                     "aliases": meta.get("aliases") or [], "handles": meta.get("handles") or {},
                     "scope": meta.get("scope") or [], "edges": meta.get("edges") or {},
                     "status": meta.get("status", "active")}
    with open(os.path.join(state_dir(), "kb-index.json"), "w") as fh:
        json.dump(out, fh)
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lstrip("@").lower())


def resolve(idx: dict, mention: str, typ: str | None = None) -> list[str]:
    m = _norm(mention)
    if m.startswith("[[") and m.endswith("]]"):
        m = m[2:-2]
    hits = []
    for slug, info in idx.items():
        if typ and info["type"] != typ:
            continue
        names = {slug, _norm(info["title"])} | {_norm(a) for a in info["aliases"]} | \
                {_norm(v) for v in info["handles"].values() if isinstance(v, str)}
        if m in names or slugify(m) == slug:
            hits.append(slug)
    return sorted(hits)


# ---------------------------------------------------------------- bodies

def person_body(title: str, meta: dict) -> str:
    h = meta.get("handles") or {}
    rows = [("Role", meta.get("role", "")), ("Team", meta.get("team", "")),
            ("Reports to", meta.get("reports_to", "")), ("Location", meta.get("location", ""))]
    rows += [(k.capitalize() if k != "github" else "GitHub", v) for k, v in sorted(h.items())]
    table = "\n".join("| %s | %s |" % r for r in rows)
    slug = slugify(title)
    return ("# %s\n\n## Overview\n\n| | |\n|---|---|\n%s\n\n## Facts\n\n## Notes\n- [[%s-interactions|Interactions]]\n"
            % (title, table, slug))


def rerender_person(meta: dict, body: str) -> str:
    new_table = person_body(meta["title"], meta).split("## Facts")[0]
    if "## Overview" in body and "## Facts" in body:
        head = body.split("## Overview")[0]
        return head + "## Overview" + new_table.split("## Overview", 1)[1] + "## Facts" + body.split("## Facts", 1)[1]
    return body


def generic_body(title: str) -> str:
    return "# %s\n\n## Facts\n" % title


def add_fact(body: str, line: str) -> tuple[str, bool]:
    if line in body:
        return body, False
    if "## Facts" not in body:
        body = body.rstrip("\n") + "\n\n## Facts\n"
    head, tail = body.split("## Facts", 1)
    tail_lines = tail.split("\n")
    insert_at = 1
    while insert_at < len(tail_lines) and (tail_lines[insert_at].startswith("- ") or tail_lines[insert_at] == ""):
        if tail_lines[insert_at] == "" and insert_at > 1 and not tail_lines[insert_at - 1].startswith("- "):
            break
        insert_at += 1
    while insert_at > 1 and tail_lines[insert_at - 1] == "":
        insert_at -= 1
    tail_lines.insert(insert_at, line)
    if insert_at == 1:
        tail_lines.insert(1, "")
    return head + "## Facts" + "\n".join(tail_lines), True


# ----------------------------------------------------------------- inbox

def inbox_dir() -> str:
    d = os.path.join(state_dir(), "kb-inbox")
    os.makedirs(d, exist_ok=True)
    return d


def hold(pid: str, kind: str, reason: str, payload: dict, source: dict) -> str:
    digest = hashlib.sha1(json.dumps([kind, payload], sort_keys=True).encode()).hexdigest()[:10]
    item = {"id": digest, "proposal": pid, "kind": kind, "reason": reason, "payload": payload,
            "source": source, "created": today()}
    path = os.path.join(inbox_dir(), "%s.json" % digest)
    if not os.path.exists(path):
        with open(path, "w") as fh:
            json.dump(item, fh, indent=1)
    return digest


def held_items() -> list[dict]:
    out = []
    for f in sorted(os.listdir(inbox_dir())):
        if f.endswith(".json"):
            with open(os.path.join(inbox_dir(), f)) as fh:
                out.append(json.load(fh))
    return out


def _drop(item_id: str) -> bool:
    path = os.path.join(inbox_dir(), "%s.json" % item_id)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


# ------------------------------------------------------------------ apply

def _applied_path() -> str:
    return os.path.join(state_dir(), "kb-applied.json")


def _applied() -> dict:
    try:
        with open(_applied_path()) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _ref_of(source: dict) -> str:
    return source.get("ref", "")


def _fact_final(f: dict) -> str | None:
    """None if the fact may land; else the hold reason."""
    if f.get("basis") not in FINAL:
        return "tentative"
    if f.get("basis") == "stated" and not (f.get("quote") or "").strip():
        return "stated without a quoted source span"
    return None


class Writer:
    """Collects the writes of one apply so --dry-run can report them without touching disk."""

    def __init__(self, root: str, dry: bool):
        self.root, self.dry, self.log = root, dry, []
        self.cache: dict[str, tuple[dict, str]] = {}

    def read(self, path: str) -> tuple[dict, str]:
        if path in self.cache:
            return self.cache[path]
        if not os.path.exists(path):
            return {}, ""
        with open(path) as fh:
            return parse(fh.read())

    def write(self, path: str, meta: dict, body: str, what: str) -> None:
        self.cache[path] = (meta, body)
        self.log.append("%s %s" % (what, os.path.relpath(path, os.path.dirname(os.path.dirname(self.root)))))
        if not self.dry:
            write_note(path, meta, body)


def _new_entity(w: Writer, typ: str, title: str, scope: list, aliases: list, ref: str) -> str:
    slug = slugify(title)
    meta = {"title": title, "type": typ, "scope": scope or ["general"], "status": "active",
            "aliases": aliases, "refs": [ref] if ref else [], "edges": {}, "created": today(), "updated": today()}
    if typ == "person":
        meta.update(part="overview", handles={})
        body = person_body(title, meta)
        w.write(interactions_path(w.root, slug), {
            "title": "%s — interactions" % title, "type": "person-part", "part": "interactions",
            "person": link(slug), "refs": [], "created": today(), "updated": today()},
            "# %s — interactions\n\n" % title, "create")
    else:
        body = generic_body(title)
    w.write(note_path(w.root, typ, slug), meta, body, "create")
    return slug


def _fold(w: Writer, idx: dict, slug: str, facts: list, source: dict, pid: str, held: list) -> None:
    info = idx[slug]
    meta, body = w.read(info["path"])
    ref = _ref_of(source)
    changed = False
    for f in facts:
        if "field" in f:
            key = f["field"]
            parent, _, leaf = key.partition(".")
            cur = (meta.get(parent) or {}).get(leaf) if leaf else meta.get(key)
            if cur in (None, ""):
                if leaf:
                    meta.setdefault(parent, {})[leaf] = f["value"]
                else:
                    meta[key] = f["value"]
                changed = True
            elif cur != f["value"]:
                held.append(hold(pid, "contradiction", "%s is %r, source says %r" % (key, cur, f["value"]),
                                 {"slug": slug, "fact": f}, source))
        elif "interaction" in f and info["type"] == "person":
            ip = interactions_path(w.root, slug)
            imeta, ibody = w.read(ip)
            line = "- %s — %s — %s" % (source.get("date", today()), f["interaction"], ref)
            if line not in ibody:
                imeta["updated"] = today()
                imeta["refs"] = sorted(set(imeta.get("refs", [])) | {ref})
                w.write(ip, imeta, ibody.rstrip("\n") + "\n" + line + "\n", "update")
        else:
            body, added = add_fact(body, "- %s — %s" % (f.get("text") or f.get("interaction"), ref))
            changed = changed or added
    if changed:
        meta["refs"] = sorted(set(meta.get("refs") or []) | {ref})
        meta["updated"] = today()
        if info["type"] == "person":
            body = rerender_person(meta, body)
        w.write(info["path"], meta, body, "update")


def _write_decision(w: Writer, idx: dict, d: dict, source: dict) -> str:
    slug = slugify(d["title"])
    def links(names):
        out = []
        for n in names or []:
            hits = resolve(idx, n)
            out.append(link(hits[0]) if len(hits) == 1 else n)
        return [x for x in out if x.startswith("[[")]
    edges = {k: v for k, v in (("evidence", links(d.get("evidence"))), ("decided_by", links(d.get("decided_by"))),
                               ("supersedes", links(d.get("supersedes")))) if v}
    refs = sorted({d["signoff"], _ref_of(source)} | {b for b in d["binds_to"] if b != "operator"})
    meta = {"title": d["title"], "type": "decision", "scope": d["scope"], "status": "active",
            "decided": source.get("date", today()), "binds_to": d["binds_to"], "refs": refs, "edges": edges,
            "created": today(), "updated": today()}
    body = ("# %s\n\n## Context\n%s\n\n## Decision\n%s\n\n## Why\n%s\n\n## Sign-off\n%s\n"
            % (d["title"], d.get("context", ""), d["decision"], d["why"], d["signoff"]))
    w.write(note_path(w.root, "decision", slug), meta, body, "create")
    for old in edges.get("supersedes", []):
        s = old[2:-2]
        if s in idx:
            om, ob = w.read(idx[s]["path"])
            om["status"], om["updated"] = "superseded", today()
            w.write(idx[s]["path"], om, ob, "supersede")
    return slug


def apply(proposal: dict, dry: bool = False, workspace: str | None = None) -> dict:
    schema = json.load(open(SCHEMA_PATH))
    errs = schema_lite.validate(proposal, {"$ref": "#/$defs/proposal"}, schema)
    if errs:
        raise ValueError("proposal invalid: " + "; ".join(errs[:5]))
    body = {k: v for k, v in proposal.items() if k != "$comment"}
    pid = hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]
    root = kb_root(workspace)
    with kb_lock():
        if pid in _applied():
            return {"proposal": pid, "status": "already applied", "writes": [], "held": []}
        w = Writer(root, dry)
        idx = index(root) if os.path.isdir(root) else {}
        source, held = proposal["source"], []
        for ent in proposal.get("entities", []):
            finals = [f for f in ent["facts"] if _fact_final(f) is None]
            for f in ent["facts"]:
                why = _fact_final(f)
                if why:
                    held.append(hold(pid, "fact", why, {"mention": ent["mention"], "type": ent["type"],
                                                        "scope": ent.get("scope"), "fact": f}, source))
            hits = resolve(idx, ent["mention"], ent["type"])
            if len(hits) > 1:
                held.append(hold(pid, "ambiguous", "matches %s" % ", ".join(hits),
                                 {"entity": dict(ent, facts=finals), "candidates": hits}, source))
            elif not hits:
                if ent["type"] in ("person", "org"):
                    held.append(hold(pid, "new-entity", "new %s needs the operator's confirmation" % ent["type"],
                                     {"entity": dict(ent, facts=finals)}, source))
                elif finals:
                    slug = _new_entity(w, ent["type"], ent["mention"], ent.get("scope"), ent.get("aliases", []),
                                       _ref_of(source))
                    idx[slug] = {"type": ent["type"], "path": note_path(root, ent["type"], slug),
                                 "title": ent["mention"], "aliases": [], "handles": {}, "scope": ent.get("scope") or [],
                                 "edges": {}, "status": "active"}
                    _fold(w, idx, slug, finals, source, pid, held)
            elif finals:
                _fold(w, idx, hits[0], finals, source, pid, held)
        for d in proposal.get("decisions", []):
            held.append(hold(pid, "decision", "waits for %s" % ", ".join(d["binds_to"]),
                             {"decision": d, "settled": []}, source))
        for e in proposal.get("edges", []):
            a, b = resolve(idx, e["from"]), resolve(idx, e["to"])
            if len(a) == 1 and len(b) == 1:
                meta, nbody = w.read(idx[a[0]]["path"])
                edges = meta.setdefault("edges", {})
                if link(b[0]) not in edges.setdefault(e["edge"], []):
                    edges[e["edge"]].append(link(b[0]))
                    meta["updated"] = today()
                    w.write(idx[a[0]]["path"], meta, nbody, "link")
            else:
                held.append(hold(pid, "edge", "endpoint unresolved or ambiguous", {"edge": e}, source))
        if not dry:
            done = _applied()
            done[pid] = {"source": source, "date": today()}
            with open(_applied_path(), "w") as fh:
                json.dump(done, fh, indent=1)
            _release_finalized(root)
        return {"proposal": pid, "status": "dry-run" if dry else "applied", "writes": w.log, "held": held}


def _release_finalized(root: str) -> None:
    """A held tentative fact whose text has since landed (from a final source) is no longer pending."""
    idx = index(root)
    for item in held_items():
        if item["kind"] != "fact":
            continue
        hits = resolve(idx, item["payload"]["mention"], item["payload"]["type"])
        text = item["payload"]["fact"].get("text")
        if len(hits) == 1 and text:
            with open(idx[hits[0]]["path"]) as fh:
                if ("- %s — " % text) in fh.read():
                    _drop(item["id"])


# ------------------------------------------------------------------ inbox

def confirm(item_id: str, as_slug: str | None = None, workspace: str | None = None) -> str:
    root = kb_root(workspace)
    with kb_lock():
        path = os.path.join(inbox_dir(), "%s.json" % item_id)
        if not os.path.exists(path):
            raise ValueError("no held item %s" % item_id)
        item = json.load(open(path))
        w, idx, src, p = Writer(root, False), index(root), item["source"], item["payload"]
        k = item["kind"]
        if k == "new-entity":
            ent = p["entity"]
            slug = _new_entity(w, ent["type"], ent["mention"], ent.get("scope"), ent.get("aliases", []), _ref_of(src))
            idx = index(root)
            _fold(w, idx, slug, ent["facts"], src, item["proposal"], [])
        elif k == "ambiguous":
            if as_slug not in p["candidates"]:
                raise ValueError("confirm an ambiguous mention with --as one of %s" % ", ".join(p["candidates"]))
            _fold(w, idx, as_slug, p["entity"]["facts"], src, item["proposal"], [])
        elif k == "fact":
            hits = [as_slug] if as_slug else resolve(idx, p["mention"], p["type"])
            if len(hits) != 1 or hits[0] not in idx:
                raise ValueError("entity %r not resolvable; use --as" % p["mention"])
            _fold(w, idx, hits[0], [dict(p["fact"], basis="confirmed")], src, item["proposal"], [])
        elif k == "contradiction":
            meta, body = w.read(idx[p["slug"]]["path"])
            parent, _, leaf = p["fact"]["field"].partition(".")
            if leaf:
                meta.setdefault(parent, {})[leaf] = p["fact"]["value"]
            else:
                meta[parent] = p["fact"]["value"]
            meta["updated"] = today()
            meta["refs"] = sorted(set(meta.get("refs") or []) | {_ref_of(src)})
            if meta.get("type") == "person":
                body = rerender_person(meta, body)
            w.write(idx[p["slug"]]["path"], meta, body, "update")
        elif k == "decision":
            _write_decision(w, idx, p["decision"], src)
        elif k == "edge":
            e = p["edge"]
            a, b = resolve(idx, e["from"]), resolve(idx, e["to"])
            if len(a) != 1 or len(b) != 1:
                raise ValueError("edge endpoints still unresolved")
            meta, body = w.read(idx[a[0]]["path"])
            meta.setdefault("edges", {}).setdefault(e["edge"], []).append(link(b[0]))
            w.write(idx[a[0]]["path"], meta, body, "link")
        elif k == "migration":
            m, body = p["meta"], p["body"]
            m["refs"] = sorted(set(m.get("refs") or []) | {"operator-confirmed %s" % today()})
            w.write(os.path.join(root, p["path"]), m, body, "create")
            for rel_, m_, b_ in p.get("extra", []):
                w.write(os.path.join(root, rel_), m_, b_, "create")
        os.remove(path)
        return "; ".join(w.log) or "confirmed %s" % item_id


def settle(story: str, state: str) -> str:
    done = state.lower() == "completed"
    out = []
    for item in held_items():
        if item["kind"] != "decision" or story not in item["payload"]["decision"]["binds_to"]:
            continue
        if not done:
            _drop(item["id"])
            out.append("dropped %s (%s → %s)" % (item["payload"]["decision"]["title"], story, state))
            continue
        item["payload"]["settled"] = sorted(set(item["payload"]["settled"]) | {story})
        pending = [b for b in item["payload"]["decision"]["binds_to"] if b not in item["payload"]["settled"]]
        if pending:
            with open(os.path.join(inbox_dir(), "%s.json" % item["id"]), "w") as fh:
                json.dump(item, fh, indent=1)
            out.append("%s still waits for %s" % (item["payload"]["decision"]["title"], ", ".join(pending)))
            continue
        root = kb_root()
        with kb_lock():
            slug = _write_decision(Writer(root, False), index(root), item["payload"]["decision"], item["source"])
        _drop(item["id"])
        out.append("recorded decision %s" % slug)
    return "; ".join(out) or "nothing bound to %s" % story


# ------------------------------------------------------------------ check

def check(workspace: str | None = None) -> tuple[list[str], list[str]]:
    root = kb_root(workspace)
    if not os.path.isdir(root):
        return ["%s does not exist" % KB_REL], []
    schema = json.load(open(SCHEMA_PATH))
    errs, warns = [], []
    idx = index(root)
    slugs = set(idx)
    seen_names: dict[tuple, str] = {}
    for path, slug, meta, body in walk(root):
        rel = os.path.relpath(path, root)
        if meta.get("type") == "person-part":
            errs += ["%s %s" % (rel, e) for e in schema_lite.validate(meta, {"$ref": "#/$defs/person_part"}, schema)]
            continue
        errs += ["%s %s" % (rel, e) for e in schema_lite.validate(meta, {"$ref": "#/$defs/common"}, schema)]
        for name in [meta.get("title", "")] + list(meta.get("aliases") or []):
            key = (meta.get("type"), _norm(name))
            if key in seen_names and seen_names[key] != slug:
                errs.append("%s: name %r also used by %s" % (rel, name, seen_names[key]))
            seen_names[key] = slug
        for edge, targets in (meta.get("edges") or {}).items():
            for t in targets:
                m = LINK_RE.match(t)
                if m and m.group(1) not in slugs:
                    errs.append("%s: %s → %s does not resolve" % (rel, edge, t))
        if meta.get("type") == "decision" and not (meta.get("edges") or {}).get("evidence"):
            (warns if meta.get("migrated_from") else errs).append("%s: decision without evidence" % rel)
        if "## Facts" in body:
            for line in body.split("## Facts", 1)[1].split("\n## ")[0].splitlines():
                if line.startswith("- ") and " — " not in line:
                    errs.append("%s: fact without a ref: %s" % (rel, line[:60]))
    return errs, warns


def search(root: str, typ=None, scope=None, text=None, edge=None, links_to=None, orphans=False) -> list[str]:
    idx = index(root)
    inbound = {s: 0 for s in idx}
    for s, info in idx.items():
        for targets in info["edges"].values():
            for t in targets:
                m = LINK_RE.match(t)
                if m and m.group(1) in inbound:
                    inbound[m.group(1)] += 1
    out = []
    for s, info in sorted(idx.items()):
        if typ and info["type"] != typ or scope and scope not in info["scope"]:
            continue
        if edge and not info["edges"].get(edge):
            continue
        if links_to and not any(link(links_to) in v for v in info["edges"].values()):
            continue
        if orphans and (inbound[s] or any(info["edges"].values())):
            continue
        if text and text.lower() not in open(info["path"]).read().lower():
            continue
        out.append("%s\t%s\t%s" % (info["type"], s, info["title"]))
    return out


# ---------------------------------------------------------------- migrate

REF_LINE = re.compile(r"^\*\*(?:Reference|References|Source|Sources)s?:\*\*\s*(.+)$", re.M)
INLINE_REF = re.compile(r"\bsc-\d{5,}\b|\b[\w.-]+/[\w.-]+#\d+\b|\bPR #\d{4,}\b|\bgranola:[\w-]+\b")
PERSON_LINE = re.compile(r"^\*\*(Email|Shortcut|Slack|GitHub|Team|Role|Role / title|Owns|Location):\*\*\s*(.+)$", re.M)


def _status(raw) -> tuple[str, list[str]]:
    raw = str(raw or "active")
    links = ["[[%s]]" % m for m in LINK_RE.findall(raw)]
    return ("superseded" if raw.lower().startswith("superseded") else "active"), links


def migrate_plan(workspace: str | None = None) -> dict:
    ws = workspace or env.workspace_root()
    vault, root = os.path.join(ws, VAULT_REL), kb_root(ws)
    writes, inbox, report = [], [], []
    for dirpath, _dirs, files in os.walk(vault):
        if "/." in dirpath or "_templates" in dirpath:
            continue
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            src = os.path.join(dirpath, f)
            meta, body = parse(open(src).read())
            slug, typ_old, extra = f[:-3], meta.get("type"), []
            refs = []
            for k in ("reference", "shortcut"):
                if meta.get(k):
                    refs += [str(meta[k])] if not isinstance(meta[k], list) else [str(x) for x in meta[k]]
            refs += [m.strip() for m in REF_LINE.findall(body)]
            refs += sorted(set(INLINE_REF.findall(body)) - set(refs))
            area = meta.get("area") or "general"
            scope = ["general"] if area in ("company", "general") else [area]
            status, sup_links = _status(meta.get("status"))
            edges = {}
            for k_old, k_new in (("relates_to", "relates_to"), ("supersedes", "supersedes"), ("grounded_by", "evidence")):
                vals = meta.get(k_old)
                if vals:
                    vals = vals if isinstance(vals, list) else [vals]
                    edges[k_new] = ["[[%s]]" % LINK_RE.findall(v)[0] if LINK_RE.findall(str(v)) else "[[%s]]" % str(v).strip("[]")
                                    for v in vals]
            if sup_links or meta.get("superseded_by"):
                edges.setdefault("relates_to", []).extend(sup_links)
            new = {"title": meta.get("title", slug), "scope": scope, "status": status, "refs": refs, "edges": edges,
                   "tags": meta.get("tags") or [], "created": str(meta.get("created", today())),
                   "updated": str(meta.get("updated", today())), "migrated_from": os.path.relpath(src, ws)}
            if meta.get("superseded_by"):
                new["status"] = "superseded"
            if typ_old == "decision":
                new["type"] = "decision"
                rel = os.path.join("decision", "%s.md" % slug)
                new_body = body
            elif typ_old == "person":
                new.update(type="person", part="overview", handles={})
                for k, v in PERSON_LINE.findall(body):
                    k = k.lower()
                    if k in ("email", "shortcut", "slack", "github"):
                        new["handles"][k] = v.strip()
                    elif k.startswith("role"):
                        new["role"] = v.strip()
                    elif k == "team":
                        new["team"] = v.strip()
                    elif k == "location":
                        new["location"] = v.strip()
                new["aliases"] = [new["title"].split()[0]] if " " in new["title"] else []
                rel = os.path.join("person", slug, "%s.md" % slug)
                parts = re.split(r"^## Interactions\s*$", body, flags=re.M)
                new_body = parts[0]
                if len(parts) > 1:
                    inter = parts[1].split("\n## ")[0]
                    extra.append((os.path.join("person", slug, "%s-interactions.md" % slug), {
                        "title": "%s — interactions" % new["title"], "type": "person-part", "part": "interactions",
                        "person": link(slug), "refs": refs, "created": new["created"], "updated": new["updated"]},
                        "# %s — interactions\n%s" % (new["title"], inter)))
                    new_body += "\n## Notes\n- [[%s-interactions|Interactions]]\n" % slug
            else:
                new["type"] = "topic"
                rel = os.path.join("topic", "%s.md" % slug)
                new_body = body
            if not refs:
                inbox.append({"path": rel, "meta": new, "body": new_body, "reason": "no reference on the note",
                              "extra": [[r_, m_, b_] for r_, m_, b_ in extra]})
                report.append("inbox   %s ← %s (no reference)" % (rel, new["migrated_from"]))
            else:
                writes.append((rel, new, new_body))
                writes.extend(extra)
                report.append("write   %s ← %s" % (rel, new["migrated_from"]))
    return {"writes": writes, "inbox": inbox, "report": report, "root": root}


def migrate(write: bool = False, workspace: str | None = None) -> dict:
    p = migrate_plan(workspace)
    if write:
        with kb_lock():
            if os.path.isdir(p["root"]) and os.listdir(p["root"]):
                raise ValueError("%s is not empty; migration writes into an empty KB only" % KB_REL)
            for rel, meta, body in p["writes"]:
                write_note(os.path.join(p["root"], rel), meta, body)
            for item in p["inbox"]:
                hold("migration", "migration", item["reason"],
                     {"path": item["path"], "meta": item["meta"], "body": item["body"], "extra": item["extra"]},
                     {"kind": "migration", "ref": item["meta"]["migrated_from"], "date": today()})
    return p


# -------------------------------------------------------------------- CLI

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="kb.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index")
    r = sub.add_parser("resolve")
    r.add_argument("mention")
    r.add_argument("--type", choices=TYPES)
    s = sub.add_parser("search")
    s.add_argument("--type", choices=TYPES)
    s.add_argument("--scope")
    s.add_argument("--text")
    s.add_argument("--edge", choices=EDGES)
    s.add_argument("--links-to")
    s.add_argument("--orphans", action="store_true")
    n = sub.add_parser("new")
    n.add_argument("type", choices=TYPES[:-1])
    n.add_argument("title")
    n.add_argument("--scope", action="append")
    a_ = sub.add_parser("apply")
    a_.add_argument("proposal")
    a_.add_argument("--dry-run", action="store_true")
    i = sub.add_parser("inbox")
    i.add_argument("action", nargs="?", default="list", choices=["list", "confirm", "drop", "settle"])
    i.add_argument("id", nargs="?")
    i.add_argument("--as", dest="as_slug")
    i.add_argument("--story")
    i.add_argument("--state", default="Completed")
    sub.add_parser("check")
    m = sub.add_parser("migrate")
    m.add_argument("--write", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    root = kb_root()
    try:
        if a.cmd == "index":
            print("%d notes indexed" % len(index(root)))
        elif a.cmd == "resolve":
            hits = resolve(index(root), a.mention, a.type)
            print("\n".join(hits))
            return 0 if len(hits) == 1 else 1
        elif a.cmd == "search":
            print("\n".join(search(root, a.type, a.scope, a.text, a.edge, a.links_to, a.orphans)))
        elif a.cmd == "new":
            with kb_lock():
                print(_new_entity(Writer(root, False), a.type, a.title, a.scope or ["general"], [], "operator"))
        elif a.cmd == "apply":
            res = apply(json.load(open(a.proposal)), dry=a.dry_run)
            print(json.dumps(res, indent=1))
        elif a.cmd == "inbox":
            if a.action == "list":
                for it in held_items():
                    print("%s\t%s\t%s\t%s" % (it["id"], it["kind"], it["reason"], it["source"].get("ref", "")))
            elif a.action == "confirm":
                print(confirm(a.id, a.as_slug))
            elif a.action == "drop":
                print("dropped" if _drop(a.id) else "no such item")
            elif a.action == "settle":
                if not a.story:
                    ap.error("settle needs --story")
                print(settle(a.story, a.state))
        elif a.cmd == "check":
            errs, warns = check()
            for e in errs:
                print("error: " + e)
            for w in warns:
                print("warning: " + w)
            print("kb check: %d error(s), %d warning(s)" % (len(errs), len(warns)))
            return 1 if errs else 0
        elif a.cmd == "migrate":
            p = migrate(a.write)
            if a.json:
                print(json.dumps({"write": len(p["writes"]), "inbox": len(p["inbox"]), "report": p["report"]}, indent=1))
            else:
                print("\n".join(p["report"]))
                print("migrate: %d to write, %d to the inbox%s" % (len(p["writes"]), len(p["inbox"]),
                                                                   " — written" if a.write else " (dry run)"))
    except (ValueError, OSError) as exc:
        print("kb: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
