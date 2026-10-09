import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tracker  # noqa: E402


class Fake:
    name = "fake"

    def __init__(self, drop_writes=False):
        self.story = {"id": "sc-1", "state": "Ready for Development", "labels": ["besstie"], "owner_ids": ["u2"],
                      "description": "d"}
        self.drop = drop_writes
        self.writes = 0
        self.comments = []

    def get(self, sid):
        return {k: (list(v) if isinstance(v, list) else v) for k, v in self.story.items()}

    def update(self, sid, cur, **change):
        self.writes += 1
        if not self.drop:
            self.story.update(change)

    def comment(self, sid, text):
        self.comments.append(text)


class TrackerTest(unittest.TestCase):
    def test_owner_is_added_never_replaced_and_repeat_is_a_no_op(self):
        fake = Fake()
        t = tracker.Tracker(fake)
        self.assertEqual(t.add_owner("sc-1", "u1")["owner_ids"], ["u2", "u1"])
        t.add_owner("sc-1", "u1")
        self.assertEqual(fake.writes, 1)

    def test_labels_and_state_are_read_back(self):
        fake = Fake()
        t = tracker.Tracker(fake)
        t.add_label("sc-1", "agent-driven")
        t.add_label("sc-1", "blocked")
        self.assertEqual(t.remove_label("sc-1", "blocked")["labels"], ["besstie", "agent-driven"])
        self.assertEqual(t.set_state("sc-1", "In Development")["state"], "In Development")

    def test_a_write_the_read_back_does_not_show_raises(self):
        with self.assertRaises(tracker.TrackerError):
            tracker.Tracker(Fake(drop_writes=True)).add_label("sc-1", "blocked")

    def test_comment_needs_its_marker(self):
        fake = Fake()
        t = tracker.Tracker(fake)
        with self.assertRaises(tracker.TrackerError):
            t.comment("sc-1", "no marker", "<!-- prometheus:stop:sc-1:1 -->")
        t.comment("sc-1", "Stopped <!-- prometheus:stop:sc-1:1 -->", "<!-- prometheus:stop:sc-1:1 -->")
        self.assertEqual(len(fake.comments), 1)

    def test_backend_falls_back_to_mcp_without_a_working_token(self):
        tracker._backend = None
        old = os.environ.pop("SHORTCUT_API_TOKEN", None)
        try:
            self.assertEqual(tracker.backend().name, "mcp")
        finally:
            tracker._backend = None
            if old is not None:
                os.environ["SHORTCUT_API_TOKEN"] = old


if __name__ == "__main__":
    unittest.main()
