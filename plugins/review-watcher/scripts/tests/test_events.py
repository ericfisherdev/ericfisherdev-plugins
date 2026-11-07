import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import events  # noqa: E402


class EventsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, "watcher.log")
        self.lines = []

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, dry_run=False, log=None):
        return events.Events(log or self.log, out=self.lines.append,
                             now=lambda: datetime(2026, 10, 30, 9, 15, 0), dry_run=dry_run)

    def written(self):
        with open(self.log, encoding="utf-8") as fh:
            return fh.read().splitlines()

    def test_should_list_exactly_the_review_outcomes(self):
        self.assertEqual(list(events.OUTCOMES), ["posted", "skipped", "no-op", "failed"])
        self.assertNotIn("pushed", events.OUTCOMES)
        for meaning in events.OUTCOMES.values():
            self.assertIsInstance(meaning, str)

    def test_should_name_the_directory_at_the_end_of_the_dispatched_line(self):
        ev = self.make()
        ev.emit("dispatched", repo="acme/widgets", pr=1, session="Rev PR#1 acme/widgets", summary="requested",
                cwd="C:/work/wt-x")
        self.assertTrue(self.lines[-1].endswith("Rev PR#1 acme/widgets requested in C:/work/wt-x"), self.lines[-1])
        ev.emit("dispatched", repo="acme/widgets", pr=2, cwd="/w")
        self.assertTrue(self.lines[-1].endswith("acme/widgets#2 in /w"), self.lines[-1])

    def test_should_print_and_append_one_line_per_event(self):
        ev = self.make()
        ev.emit("finished", repo="acme/widgets", pr=7, session="Rev PR#7 acme/widgets",
                summary="posted, head abc1234")
        ev.emit("stale-session", session="Rev PR#4 acme/gadgets", repo="acme/gadgets", pr=4, idle_minutes=46)
        written = self.written()
        self.assertEqual(written, self.lines)
        self.assertEqual(written[0], "[2026-10-30 09:15:00] finished acme/widgets#7 Rev PR#7 acme/widgets "
                                     "posted, head abc1234")
        self.assertIn("idle 46 min", written[1])
        self.assertIn("acme/gadgets#4", written[1])

    def test_should_show_the_repo_alone_when_there_is_no_pr(self):
        self.make().emit("follow-up", repo="acme/widgets", summary="x")
        self.assertEqual(self.lines[-1], "[2026-10-30 09:15:00] follow-up acme/widgets x")

    def test_should_note_the_start_once_and_name_the_log(self):
        ev = self.make()
        ev.start_note()
        ev.start_note()
        self.assertEqual(len(self.lines), 1)
        self.assertIn(self.log, self.lines[0])
        self.assertEqual(self.written(), self.lines)

    def test_should_write_no_log_in_a_dry_run(self):
        ev = self.make(dry_run=True)
        ev.start_note()
        ev.emit("dispatched", repo="acme/widgets", pr=1)
        ev.note("tick")
        self.assertFalse(os.path.exists(self.log))
        self.assertEqual(len(self.lines), 3)
        self.assertIn("dry run", self.lines[0])

    def test_should_print_and_not_raise_when_the_log_cannot_be_written(self):
        unwritable = os.path.join(self.tmp.name, "missing-dir", "watcher.log")
        self.make(log=unwritable).note("tick")
        self.assertEqual(self.lines[0], "[2026-10-30 09:15:00] tick")
        self.assertTrue(self.lines[1].startswith(f"could not write the log {unwritable}"), self.lines[1])


if __name__ == "__main__":
    unittest.main()
