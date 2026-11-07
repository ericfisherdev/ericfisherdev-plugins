import contextlib
import functools
import io
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ledger  # noqa: E402
import report  # noqa: E402

KEY = "acme/widgets#7"
SESSION = "Rev PR#7 acme/widgets"


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "ledger.json")
        with ledger.update(self.path) as data:
            data["active"][KEY] = {"session": SESSION, "repo": "acme/widgets", "pr": 7}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = report.main(["--ledger", self.path, *args])
        return code, json.loads(out.getvalue())

    def entry(self):
        return ledger.read(self.path)["active"][KEY]

    def test_should_write_the_report_onto_the_active_entry(self):
        code, out = self.run_cli("--repo", "acme/widgets", "--pr", "7", "--session", SESSION,
                                 "--outcome", "posted", "--head", "abc1234")
        self.assertEqual(code, 0)
        self.assertEqual(out, {"ok": True, "key": KEY, "outcome": "posted", "replaced": False})
        saved = self.entry()["report"]
        self.assertEqual((saved["outcome"], saved["head_sha"]), ("posted", "abc1234"))
        self.assertRegex(saved["finished_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(self.entry()["session"], SESSION)

    def test_should_fail_when_no_session_is_in_flight(self):
        code, out = self.run_cli("--repo", "acme/widgets", "--pr", "8", "--outcome", "posted")
        self.assertEqual(code, 1)
        self.assertEqual(out, {"error": "no review session in flight for acme/widgets#8"})
        code, out = self.run_cli("--repo", "other/widgets", "--pr", "7", "--outcome", "posted")
        self.assertEqual(code, 1)
        self.assertEqual(out, {"error": "no review session in flight for other/widgets#7"})
        self.assertNotIn("report", self.entry())

    def test_should_fail_on_a_session_mismatch(self):
        code, out = self.run_cli("--repo", "acme/widgets", "--pr", "7", "--session", "Rev PR#7 other",
                                 "--outcome", "posted")
        self.assertEqual(code, 1)
        self.assertIn("session mismatch", out["error"])
        self.assertNotIn("report", self.entry())

    def test_should_refuse_a_late_report_from_an_earlier_dispatch(self):
        with ledger.update(self.path) as data:
            data["active"][KEY]["dispatch"] = "new12345"
        args = ("--repo", "acme/widgets", "--pr", "7", "--session", SESSION)
        code, out = self.run_cli(*args, "--dispatch", "old12345", "--outcome", "posted")
        self.assertEqual(code, 1)
        self.assertIn("dispatch mismatch", out["error"])
        self.assertNotIn("report", self.entry())
        code, out = self.run_cli(*args, "--dispatch", "new12345", "--outcome", "posted")
        self.assertEqual(code, 0)
        self.assertEqual(self.entry()["report"]["outcome"], "posted")

    def test_should_wait_out_a_crashed_writers_lock_until_it_is_breakable(self):
        with open(self.path + ".lock", "w", encoding="utf-8") as fh:
            fh.write("{}")
        now = [time.time()]

        def sleep(_seconds):
            now[0] += 1

        waiting = functools.partial(ledger.update, clock=lambda: now[0], sleep=sleep)
        with mock.patch.object(report.ledger, "update", waiting):
            report.record(self.path, "acme/widgets", 7, "posted")
        self.assertEqual(self.entry()["report"]["outcome"], "posted")

    def test_should_clear_a_stuck_pr_without_a_session_or_head(self):
        code, out = self.run_cli("--repo", "acme/widgets", "--pr", "7", "--outcome", "failed")
        self.assertEqual(code, 0)
        self.assertEqual(self.entry()["report"]["outcome"], "failed")
        self.assertIsNone(self.entry()["report"]["head_sha"])

    def test_should_overwrite_an_earlier_report_and_say_so(self):
        args = ("--repo", "acme/widgets", "--pr", "7")
        self.run_cli(*args, "--outcome", "failed")
        code, out = self.run_cli(*args, "--outcome", "posted", "--head", "deadbeef")
        self.assertTrue(out["replaced"])
        self.assertEqual(self.entry()["report"]["outcome"], "posted")

    def test_should_reject_a_bad_head_sha(self):
        for head in ("XYZ1234", "abc12", "ABC1234", "abc1234;rm"):
            code, out = self.run_cli("--repo", "acme/widgets", "--pr", "7", "--outcome", "posted", "--head", head)
            self.assertEqual(code, 1, head)
            self.assertIn("invalid head", out["error"])
        self.assertNotIn("report", self.entry())

    def test_should_reject_a_repo_that_is_not_owner_and_name(self):
        for repo in ("widgets", "bad repo", "acme/..", "acme/widgets/x", "/widgets"):
            code, out = self.run_cli("--repo", repo, "--pr", "7", "--outcome", "posted")
            self.assertEqual(code, 1, repo)
            self.assertIn("invalid repo", out["error"])
            self.assertIn("owner/name", out["error"])
        self.assertNotIn("report", self.entry())

    def test_should_accept_every_review_outcome_and_nothing_else(self):
        for outcome in ("posted", "skipped", "no-op", "failed"):
            code, out = self.run_cli("--repo", "acme/widgets", "--pr", "7", "--outcome", outcome)
            self.assertEqual((code, out["outcome"]), (0, outcome))
        with contextlib.redirect_stderr(io.StringIO()):
            for outcome in ("pushed", "done"):
                with self.assertRaises(SystemExit, msg=outcome):
                    report.main(["--ledger", self.path, "--repo", "acme/widgets", "--pr", "7",
                                 "--outcome", outcome])

    def test_should_reject_a_non_numeric_pr_and_the_removed_kind_flag(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                report.main(["--ledger", self.path, "--repo", "acme/widgets", "--pr", "x", "--outcome", "posted"])
            with self.assertRaises(SystemExit):
                report.main(["--ledger", self.path, "--kind", "review", "--repo", "acme/widgets", "--pr", "7",
                             "--outcome", "posted"])

    def test_should_report_a_corrupt_ledger_as_an_error(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        code, out = self.run_cli("--repo", "acme/widgets", "--pr", "7", "--outcome", "posted")
        self.assertEqual(code, 1)
        self.assertIn("not valid JSON", out["error"])

    def test_should_default_the_ledger_to_the_review_watcher_state_dir(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.tmp.name}):
            state = os.path.join(self.tmp.name, "review-watcher", "ledger.json")
            with ledger.update(state) as data:
                data["active"][KEY] = {"session": SESSION, "repo": "acme/widgets", "pr": 7}
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = report.main(["--repo", "acme/widgets", "--pr", "7", "--outcome", "no-op"])
        self.assertEqual(code, 0)
        self.assertEqual(ledger.read(state)["active"][KEY]["report"]["outcome"], "no-op")
        self.assertNotIn("report", self.entry())


if __name__ == "__main__":
    unittest.main()
