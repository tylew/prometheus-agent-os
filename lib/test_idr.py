import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import idr  # noqa: E402

GOOD = """# IDR: Show the accepted interval widths beside the upload

**Story:** [sc-110005](https://app.shortcut.com/voltus/story/110005)

## Approach

The tooltip sits beside the file input in both upload places and reads the width bounds from the shared
constants. Nothing in the upload path changes.

```mermaid
flowchart LR
  A[Upload dialog] --> T[Info tooltip]
  B[Drop zone] --> T
```

## Decisions

1. **One shared tooltip component.** Why: both places show the same rules. Instead of: two copies that drift.

## Where the scenarios are tested

The package's component tests render the dialog and the drop zone.

## Rollout and observability

None applies: copy only, no flag, no new data.
"""


class CheckTest(unittest.TestCase):
    def test_conforming_idr_passes(self):
        self.assertEqual(idr.check(GOOD), [])

    def test_missing_and_misordered_sections(self):
        bad = GOOD.replace("## Decisions", "## Choices")
        self.assertTrue(any("missing section ## Decisions" in p for p in idr.check(bad)))
        swapped = GOOD.replace("## Approach", "## TMP").replace("## Rollout and observability", "## Approach") \
                      .replace("## TMP", "## Rollout and observability")
        self.assertTrue(any("out of order" in p for p in idr.check(swapped)))

    def test_budget(self):
        long = GOOD.replace("Nothing in the upload path changes.", "word " * 420)
        self.assertTrue(any("over the 400 budget" in p for p in idr.check(long)))
        longer = GOOD.replace("Nothing in the upload path changes.", "word " * 700)
        self.assertTrue(any("600 hard stop" in p for p in idr.check(longer)))

    def test_words_in_fences_do_not_count(self):
        fenced = GOOD.replace("```mermaid", "```mermaid\n%%" + " word" * 500)
        self.assertFalse(any("budget" in p or "hard stop" in p for p in idr.check(fenced)))

    def test_never_holds(self):
        for snippet, what in (("see lib/upload.ts:42", "file:line"), ("Scenario: Tooltip shows", "Scenario:"),
                              ("- [ ] wire it", "task list"), ("TBD later", "TBD"), ("[[DEC-0243]]", "wikilink")):
            problems = idr.check(GOOD.replace("Nothing in the upload path changes.", "\n" + snippet + "\n"))
            self.assertTrue(any(what in p for p in problems), (snippet, problems))

    def test_real_code_and_counts(self):
        code = GOOD.replace("## Decisions", "```python\nx = 1\n```\n\n## Decisions")
        self.assertTrue(any("real code" in p for p in idr.check(code)))
        many = GOOD.replace("1. **One shared", "".join("%d. **D%d.** Why: y.\n" % (i, i) for i in range(1, 8)) + "8. **One shared")
        self.assertTrue(any("decisions — at most 6" in p for p in idr.check(many)))


class BlockTest(unittest.TestCase):
    def test_insert_then_replace_keeps_the_rest(self):
        body = "## What changed\n\nCopy.\n\n## Risks\n\nNone."
        once = idr.block(body, GOOD)
        self.assertIn(idr.BEGIN, once)
        self.assertIn("<summary>IDR</summary>", once)
        self.assertTrue(once.startswith(body))
        twice = idr.block(once, GOOD.replace("Nothing in the upload path changes.", "Changed."))
        self.assertEqual(twice.count(idr.BEGIN), 1)
        self.assertIn("Changed.", twice)
        self.assertNotIn("Nothing in the upload path changes.", twice)
        self.assertTrue(twice.startswith(body))
        self.assertEqual(idr.block(twice, GOOD.replace("Nothing in the upload path changes.", "Changed.")), twice)


if __name__ == "__main__":
    unittest.main()
