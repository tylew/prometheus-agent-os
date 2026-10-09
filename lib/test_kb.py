import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import kb  # noqa: E402

SRC = {"kind": "meeting", "ref": "granola:m1", "date": "2026-10-01"}


def prop(entities=(), decisions=(), edges=(), source=SRC):
    return {"source": dict(source), "entities": list(entities), "decisions": list(decisions), "edges": list(edges)}


def fact(text, basis="decided", quote=None):
    f = {"text": text, "basis": basis}
    if quote:
        f["quote"] = quote
    return f


class Base(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        os.environ.update(WORKSPACE=self.ws, PROMETHEUS_STATE_DIR=os.path.join(self.ws, "state"),
                          PROMETHEUS_TODAY="2026-10-06")
        self.root = kb.kb_root()

    def tearDown(self):
        shutil.rmtree(self.ws)

    def read(self, rel):
        return open(os.path.join(self.root, rel)).read()

    def inbox(self, kind=None):
        return [i for i in kb.held_items() if kind is None or i["kind"] == kind]


class ApplyTest(Base):
    def test_concept_created_with_final_fact_and_ref(self):
        r = kb.apply(prop([{"mention": "CP dispatch", "type": "concept", "scope": ["besstie"],
                            "facts": [fact("Derates savings by dispatch days")]}]))
        self.assertEqual(r["held"], [])
        body = self.read("concept/cp-dispatch.md")
        self.assertIn("- Derates savings by dispatch days — granola:m1", body)
        meta, _ = kb.parse(body)
        self.assertEqual((meta["scope"], meta["refs"]), (["besstie"], ["granola:m1"]))

    def test_new_person_held_until_confirmed_then_overview_rendered(self):
        r = kb.apply(prop([{"mention": "Ariel Ng", "type": "person", "aliases": ["Ariel"], "facts": [
            {"field": "role", "value": "Head of Product", "basis": "stated", "quote": "I'm heading product"},
            {"interaction": "Asked for the org redesign doc", "basis": "decided"}]}]))
        self.assertFalse(os.path.exists(os.path.join(self.root, "person")))
        item = self.inbox("new-entity")[0]
        kb.confirm(item["id"])
        meta, body = kb.parse(self.read("person/ariel-ng/ariel-ng.md"))
        self.assertEqual((meta["role"], meta["aliases"]), ("Head of Product", ["Ariel"]))
        self.assertIn("| Role | Head of Product |", body)
        self.assertIn("Asked for the org redesign doc — granola:m1", self.read("person/ariel-ng/ariel-ng-interactions.md"))
        self.assertEqual(kb.resolve(kb.index(self.root), "ariel"), ["ariel-ng"])

    def test_tentative_and_unquoted_stated_are_held(self):
        kb.apply(prop([{"mention": "Solver", "type": "system", "scope": ["besstie"], "facts": [
            fact("Runs nightly"), fact("Might move to GPU", "tentative"), fact("Owned by Bob", "stated")]}]))
        body = self.read("system/solver.md")
        self.assertIn("Runs nightly", body)
        self.assertNotIn("GPU", body)
        self.assertNotIn("Bob", body)
        self.assertEqual(sorted(i["reason"] for i in self.inbox("fact")),
                         ["stated without a quoted source span", "tentative"])

    def test_tentative_released_when_a_final_source_states_it(self):
        kb.apply(prop([{"mention": "Solver", "type": "system", "facts": [fact("Runs nightly")]}]))
        kb.apply(prop([{"mention": "Solver", "type": "system", "facts": [fact("Moves to GPU", "tentative")]}],
                      source=dict(SRC, ref="granola:m2")))
        self.assertEqual(len(self.inbox("fact")), 1)
        kb.apply(prop([{"mention": "Solver", "type": "system", "facts": [fact("Moves to GPU", "merged")]}],
                      source={"kind": "pr", "ref": "o/r#5", "date": "2026-10-03"}))
        self.assertEqual(self.inbox("fact"), [])
        self.assertIn("- Moves to GPU — o/r#5", self.read("system/solver.md"))

    def test_contradicting_field_held_and_confirm_overwrites(self):
        kb.apply(prop([{"mention": "Org A", "type": "org", "facts": []}]))
        kb.confirm(self.inbox("new-entity")[0]["id"])
        kb.apply(prop([{"mention": "Org A", "type": "org", "facts": [{"field": "kind", "value": "customer", "basis": "decided"}]}]))
        kb.apply(prop([{"mention": "Org A", "type": "org", "facts": [{"field": "kind", "value": "vendor", "basis": "decided"}]}],
                      source=dict(SRC, ref="granola:m3")))
        held = self.inbox("contradiction")
        self.assertEqual(len(held), 1)
        self.assertEqual(kb.parse(self.read("org/org-a.md"))[0]["kind"], "customer")
        kb.confirm(held[0]["id"])
        self.assertEqual(kb.parse(self.read("org/org-a.md"))[0]["kind"], "vendor")

    def test_ambiguous_mention_held_and_confirmed_with_as(self):
        for t in ("Alex Kim", "Alex Roe"):
            kb.apply(prop([{"mention": t, "type": "person", "aliases": ["Alex"], "facts": []}],
                          source=dict(SRC, ref="granola:" + t)))
            kb.confirm(self.inbox("new-entity")[0]["id"])
        kb.apply(prop([{"mention": "Alex", "type": "person", "facts": [fact("Leads data")]}]))
        item = self.inbox("ambiguous")[0]
        with self.assertRaises(ValueError):
            kb.confirm(item["id"])
        kb.confirm(item["id"], as_slug="alex-roe")
        self.assertIn("Leads data", self.read("person/alex-roe/alex-roe.md"))

    def test_idempotent_and_dry_run(self):
        p = prop([{"mention": "Tolling", "type": "concept", "facts": [fact("A lease of capacity")]}])
        dry = kb.apply(p, dry=True)
        self.assertTrue(dry["writes"])
        self.assertFalse(os.path.exists(self.root + "/concept/tolling.md"))
        kb.apply(p)
        self.assertEqual(kb.apply(p)["status"], "already applied")
        self.assertEqual(self.read("concept/tolling.md").count("A lease of capacity"), 1)

    def test_edges_link_resolved_entities(self):
        kb.apply(prop([{"mention": "Solver", "type": "system", "facts": [fact("x")]},
                       {"mention": "Tolling", "type": "concept", "facts": [fact("y")]}],
                      edges=[{"from": "Solver", "edge": "depends_on", "to": "Tolling"},
                             {"from": "Solver", "edge": "relates_to", "to": "Nowhere"}]))
        self.assertEqual(kb.parse(self.read("system/solver.md"))[0]["edges"]["depends_on"], ["[[tolling]]"])
        self.assertEqual(len(self.inbox("edge")), 1)


class DecisionTest(Base):
    def decision(self, binds):
        return {"title": "Derate stays in the FE", "decision": "Keep it in the pro-forma", "why": "Engine ignores it",
                "basis": "decided", "signoff": "spec:x/design.md", "binds_to": binds, "scope": ["besstie"],
                "evidence": ["CP dispatch"]}

    def test_decision_waits_for_every_bound_story(self):
        kb.apply(prop([{"mention": "CP dispatch", "type": "concept", "facts": [fact("z")]}],
                      decisions=[self.decision(["sc-1", "sc-2"])]))
        self.assertIn("still waits for sc-2", kb.settle("sc-1", "Completed"))
        self.assertFalse(os.path.exists(os.path.join(self.root, "decision")))
        self.assertIn("recorded decision", kb.settle("sc-2", "Completed"))
        meta, body = kb.parse(self.read("decision/derate-stays-in-the-fe.md"))
        self.assertEqual(meta["edges"]["evidence"], ["[[cp-dispatch]]"])
        self.assertIn("## Why\nEngine ignores it", body)
        self.assertEqual(self.inbox("decision"), [])

    def test_wont_fix_drops_the_decision(self):
        kb.apply(prop(decisions=[self.decision(["sc-9"])]))
        self.assertIn("dropped", kb.settle("sc-9", "Won't Fix"))
        self.assertEqual(self.inbox(), [])
        self.assertFalse(os.path.exists(os.path.join(self.root, "decision")))

    def test_operator_bound_decision_needs_confirm(self):
        kb.apply(prop(decisions=[self.decision(["operator"])]))
        kb.confirm(self.inbox("decision")[0]["id"])
        self.assertTrue(os.path.exists(os.path.join(self.root, "decision", "derate-stays-in-the-fe.md")))

    def confirmed(self, binds, quote="keep it in the FE"):
        d = dict(self.decision(binds), basis="confirmed", signoff="operator (pm tab, 2026-10-08)")
        if quote:
            d["quote"] = quote
        return d

    def test_operator_confirmed_decision_lands_on_apply(self):
        r = kb.apply(prop(decisions=[self.confirmed(["operator"])]))
        self.assertEqual(r["held"], [])
        _, body = kb.parse(self.read("decision/derate-stays-in-the-fe.md"))
        self.assertIn("operator (pm tab, 2026-10-08)", body)
        self.assertIn("keep it in the FE", body)

    def test_confirmed_without_quote_is_held(self):
        kb.apply(prop(decisions=[self.confirmed(["operator"], quote=None)]))
        self.assertIn("without the operator's answer", self.inbox("decision")[0]["reason"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "decision")))

    def test_confirmed_story_bound_waits_for_story_only(self):
        kb.apply(prop(decisions=[self.confirmed(["sc-1", "operator"])]))
        self.assertFalse(os.path.exists(os.path.join(self.root, "decision")))
        self.assertIn("recorded decision", kb.settle("sc-1", "Completed"))
        self.assertEqual(self.inbox(), [])


class ConcurrencyCheckTest(Base):
    def test_parallel_applies_do_not_duplicate_or_lose(self):
        kb.apply(prop([{"mention": "Solver", "type": "system", "facts": [fact("base")]}]))
        files = []
        for i in range(6):
            path = os.path.join(self.ws, "p%d.json" % i)
            json.dump(prop([{"mention": "Solver", "type": "system", "facts": [fact("fact %d" % (i % 3))]}],
                           source=dict(SRC, ref="granola:c%d" % i)), open(path, "w"))
            files.append(path)
        procs = [subprocess.Popen([sys.executable, os.path.join(LIB, "kb.py"), "apply", f], stdout=subprocess.DEVNULL,
                                  env=dict(os.environ)) for f in files]
        self.assertEqual([p.wait() for p in procs], [0] * 6)
        body = self.read("system/solver.md")
        for i in range(3):
            self.assertEqual(sum(1 for l in body.splitlines() if l.startswith("- fact %d —" % i)), 2)

    def test_check_catches_dangling_edges_and_unreferenced_facts(self):
        kb.apply(prop([{"mention": "Solver", "type": "system", "facts": [fact("ok")]}]))
        path = os.path.join(self.root, "system", "solver.md")
        meta, body = kb.parse(open(path).read())
        meta["edges"] = {"relates_to": ["[[ghost]]"]}
        kb.write_note(path, meta, body + "- no ref here\n")
        errs, _ = kb.check()
        self.assertTrue(any("does not resolve" in e for e in errs))
        self.assertTrue(any("fact without a ref" in e for e in errs))


class MigrateTest(Base):
    def test_vault_mapping(self):
        v = os.path.join(self.ws, "docs", "vault")
        os.makedirs(os.path.join(v, "decisions", "besstie"))
        os.makedirs(os.path.join(v, "knowledge", "besstie"))
        os.makedirs(os.path.join(v, "people"))
        open(os.path.join(v, "decisions", "besstie", "adr-x.md"), "w").write(
            "---\ntitle: ADR X\ntype: decision\narea: besstie\nstatus: superseded by [[adr-y]]\ntags: [a, b]\n"
            "created: 2026-08-01\nupdated: 2026-08-02\nreference: sc-104815 — design confirmed\n---\n\n# ADR X\nbody\n")
        open(os.path.join(v, "knowledge", "besstie", "k.md"), "w").write(
            "---\ntitle: K\ntype: knowledge\narea: company\nstatus: active\ntags: []\ncreated: 2026-08-01\n"
            "updated: 2026-08-01\n---\n\nSee sc-101067 for why.\n")
        open(os.path.join(v, "people", "jo-doe.md"), "w").write(
            "---\ntitle: Jo Doe\ntype: person\narea: company\nstatus: active\ntags: [person]\ncreated: 2026-08-01\n"
            "updated: 2026-08-01\n---\n\n# Jo Doe\n\n**Email:** jo@x.co\n**Role:** PM\n\n## Interactions\n- met\n")
        p = kb.migrate(write=True)
        meta, _ = kb.parse(self.read("decision/adr-x.md"))
        self.assertEqual((meta["status"], meta["refs"], meta["tags"]), ("superseded", ["sc-104815 — design confirmed"], ["a", "b"]))
        self.assertEqual(meta["edges"]["relates_to"], ["[[adr-y]]"])
        k, _ = kb.parse(self.read("topic/k.md"))
        self.assertEqual((k["scope"], k["refs"]), (["general"], ["sc-101067"]))
        self.assertEqual(len(p["inbox"]), 1)
        self.assertFalse(os.path.exists(os.path.join(self.root, "person")))
        held = self.inbox("migration")[0]
        self.assertEqual(held["payload"]["meta"]["handles"], {"email": "jo@x.co"})
        self.assertEqual(held["payload"]["meta"]["role"], "PM")
        kb.confirm(held["id"])
        self.assertTrue(os.path.exists(os.path.join(self.root, "person", "jo-doe", "jo-doe.md")))
        self.assertIn("- met", self.read("person/jo-doe/jo-doe-interactions.md"))
        with self.assertRaises(ValueError):
            kb.migrate(write=True)


if __name__ == "__main__":
    unittest.main()
