import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import Dirs, Disposition, Ledger, LedgerError  # noqa: E402


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ledger" / "o__r" / "7.json"

    def test_missing_file_is_an_empty_ledger(self):
        ledger = Ledger.load(self.path)
        self.assertEqual((ledger.passes, ledger.findings), ([], {}))
        self.assertIsNone(ledger.last_closed_sha())

    def test_round_trip_and_last_closed_sha(self):
        ledger = Ledger.load(self.path)
        ledger.open_pass({"sha": "s1"})
        ledger.record("a.py:k", "s1", Disposition.PENDING, "awaiting", title="T", file="a.py", line=3)
        ledger.save()
        self.assertIsNone(Ledger.load(self.path).last_closed_sha())

        ledger.set_disposition("a.py:k", Disposition.POSTED, "posted")
        ledger.close_pass("s1", posted=1)
        ledger.save()
        reloaded = Ledger.load(self.path)
        self.assertEqual(reloaded.last_closed_sha(), "s1")
        self.assertEqual(reloaded.findings["a.py:k"]["disposition"], "posted")
        self.assertEqual(reloaded.passes[0]["posted"], 1)

    def test_an_abandoned_pass_for_the_same_sha_is_replaced(self):
        ledger = Ledger.load(self.path)
        ledger.open_pass({"sha": "s1", "kept": 1})
        ledger.open_pass({"sha": "s1", "kept": 2})
        self.assertEqual([p["kept"] for p in ledger.passes], [2])

    def test_an_abandoned_pass_does_not_hide_an_earlier_closed_one(self):
        ledger = Ledger.load(self.path)
        ledger.open_pass({"sha": "s1"})
        ledger.close_pass("s1")
        ledger.open_pass({"sha": "s2"})
        self.assertEqual(ledger.last_closed_sha(), "s1")

    def test_closing_a_pass_that_was_never_opened_fails(self):
        with self.assertRaises(LedgerError):
            Ledger.load(self.path).close_pass("nope")

    def test_corrupt_file_is_refused(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(LedgerError):
            Ledger.load(self.path)
        self.path.write_text('{"passes": {}}', encoding="utf-8")
        with self.assertRaises(LedgerError):
            Ledger.load(self.path)

    def test_summary_lines_name_disposition_location_and_reason(self):
        ledger = Ledger.load(self.path)
        ledger.record("a.py:k", "abcdef0123456", Disposition.DECLINED, "not worth it", title="T", file="a.py", line=3)
        self.assertEqual(ledger.summary_lines(), ["- [declined] a.py:3 T (reviewed at abcdef012): not worth it"])


class DirsTest(unittest.TestCase):
    def test_paths_are_per_repo_and_pr_and_outside_any_repository(self):
        dirs = Dirs(Path("/state"), "Owner/Name", 12)
        self.assertEqual(dirs.run, Path("/state/runs/Owner__Name/12"))
        self.assertEqual(dirs.tree, Path("/state/trees/Owner__Name-12"))
        self.assertEqual(dirs.ledger, Path("/state/ledger/Owner__Name/12.json"))


if __name__ == "__main__":
    unittest.main()
