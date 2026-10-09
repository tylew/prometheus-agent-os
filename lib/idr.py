#!/usr/bin/env python3
# ---
# name: idr
# description: The story's Implementation Decision Record — check one against voltus-kanban's shape and budget (sections in order, ≤400 words outside fences with 600 the hard stop, ≤2 Mermaid diagrams, ≤25 pseudocode lines, ≤6 decisions, never-holds), and keep its collapsed copy in a PR body between markers. The IDR lives at <state>/engine/stories/<sc-id>/idr.md while the story is built.
# usage: idr.py check <idr.md> [--json] | idr.py block <pr-body.md> <idr.md>  (prints the body with the IDR block inserted or replaced)
# ---
from __future__ import annotations

import json
import re
import sys

SECTIONS = ("## Approach", "## Decisions", "## Where the scenarios are tested", "## Rollout and observability")
WORDS_SOFT, WORDS_HARD = 400, 600
MAX_DIAGRAMS, MAX_PSEUDO, MAX_DECISIONS = 2, 25, 6
NEVER = (
    (re.compile(r"\b[\w./-]+\.\w{1,5}:\d+\b"), "file:line reference"),
    (re.compile(r"^\s*(Scenario|Scenario Outline):", re.M), "a Scenario: header line"),
    (re.compile(r"^\s*[-*] \[[ xX]\]", re.M), "a task list"),
    (re.compile(r"\bTBD\b|\bTODO\b"), "TBD / TODO"),
    (re.compile(r"\[\[[^\]]+\]\]"), "a wikilink"),
    (re.compile(r"\bDEC-\d{3,}\b"), "a decision id"),
)
BEGIN, END = "<!-- prometheus:idr:begin -->", "<!-- prometheus:idr:end -->"


def _fences(text: str) -> list[tuple[str, str]]:
    """(info string, body) for each fenced block."""
    return re.findall(r"^```([^\n]*)\n(.*?)^```", text, re.M | re.S)


def _prose(text: str) -> str:
    return re.sub(r"^```[^\n]*\n.*?^```", "", text, flags=re.M | re.S)


def _section(text: str, heading: str) -> str:
    m = re.search(r"^%s\s*$(.*?)(?=^## |\Z)" % re.escape(heading), text, re.M | re.S)
    return m.group(1) if m else ""


def check(text: str) -> list[str]:
    """Problems with an IDR; empty when it conforms."""
    out = []
    if not re.search(r"^# IDR: \S", text, re.M):
        out.append("missing title line '# IDR: <what the story delivers>'")
    if not re.search(r"^\*\*Story:\*\* \S", text, re.M):
        out.append("missing '**Story:** <link>' line")
    found = [h for h in SECTIONS if re.search(r"^%s\s*$" % re.escape(h), text, re.M)]
    for h in SECTIONS:
        if h not in found:
            out.append("missing section %s" % h)
    positions = [re.search(r"^%s\s*$" % re.escape(h), text, re.M).start() for h in found]
    if positions != sorted(positions):
        out.append("sections out of order (Approach, Decisions, Where the scenarios are tested, Rollout and observability)")
    prose = _prose(text)
    words = len(re.findall(r"[A-Za-z0-9][\w'’-]*", prose))
    if words > WORDS_HARD:
        out.append("%d words outside fenced blocks — over the 600 hard stop" % words)
    elif words > WORDS_SOFT:
        out.append("%d words outside fenced blocks — over the 400 budget (trim once; still over ⇒ Stop)" % words)
    fences = _fences(text)
    diagrams = [b for info, b in fences if info.strip().lower() == "mermaid"]
    if len(diagrams) > MAX_DIAGRAMS:
        out.append("%d Mermaid diagrams — at most %d" % (len(diagrams), MAX_DIAGRAMS))
    pseudo = sum(len([l for l in b.splitlines() if l.strip()]) for info, b in fences
                 if info.strip().lower() in ("", "text"))
    if pseudo > MAX_PSEUDO:
        out.append("%d pseudocode lines — at most %d" % (pseudo, MAX_PSEUDO))
    real = [info.strip() for info, _ in fences if info.strip().lower() not in ("", "text", "mermaid")]
    if real:
        out.append("real code block(s) (%s) — pseudocode only, in an untagged or text block" % ", ".join(real))
    decisions = re.findall(r"^\d+\.\s", _section(text, "## Decisions"), re.M)
    if len(decisions) > MAX_DECISIONS:
        out.append("%d decisions — at most %d" % (len(decisions), MAX_DECISIONS))
    for pat, what in NEVER:
        m = pat.search(prose)
        if m:
            out.append("never holds %s: %r" % (what, m.group(0).strip()))
    return out


def block(body: str, idr_text: str) -> str:
    """The PR body with the IDR's collapsed copy inserted at the end, or replaced in place."""
    inner = "%s\n<details><summary>IDR</summary>\n\n%s\n\n</details>\n%s" % (BEGIN, idr_text.strip(), END)
    if BEGIN in body and END in body:
        head, rest = body.split(BEGIN, 1)
        return head + inner + rest.split(END, 1)[1]
    return body.rstrip("\n") + "\n\n" + inner + "\n"


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "check":
        problems = check(open(argv[1]).read())
        if "--json" in argv:
            print(json.dumps(problems))
        else:
            print("\n".join(problems) or "ok")
        return 1 if problems else 0
    if len(argv) == 3 and argv[0] == "block":
        sys.stdout.write(block(open(argv[1]).read(), open(argv[2]).read()))
        return 0
    print("usage: idr.py check <idr.md> [--json] | idr.py block <pr-body.md> <idr.md>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
