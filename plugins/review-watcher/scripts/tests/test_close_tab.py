import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import close_tab  # noqa: E402
import ledger  # noqa: E402

REPO = "acme/widgets"
KEY = "acme/widgets#7"
DISPATCH = "d1d2d3d4"
PANE = "%12"
TMUX = "/usr/bin/tmux"
REPORT = {"outcome": "posted", "head_sha": "abc1234", "finished_at": "2026-11-10T12:00:00Z"}


class Runner:
    def __init__(self, returncode=0, stderr="", error=None):
        self.calls = []
        self.returncode = returncode
        self.stderr = stderr
        self.error = error

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if self.error:
            raise self.error
        return subprocess.CompletedProcess(cmd, self.returncode, "", self.stderr)


class CloseTabTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "ledger.json")
        self.runner = Runner()

    def tearDown(self):
        self.tmp.cleanup()

    def store(self, section="active", report=True, dispatch=DISPATCH):
        entry = {"session": "Rev PR#7 acme/widgets", "dispatch": dispatch, "repo": REPO, "pr": 7}
        if report:
            entry["report"] = REPORT
        with ledger.update(self.path) as data:
            data[section][KEY] = entry

    def close(self, env=None, which=lambda name: TMUX):
        env = {"TMUX_PANE": PANE} if env is None else env
        return close_tab.close(self.path, REPO, 7, DISPATCH, env=env, which=which, runner=self.runner)

    def test_should_kill_its_own_pane_once_the_session_reported(self):
        self.store()
        self.assertEqual(self.close(), {"ok": True, "pane": PANE})
        self.assertEqual(self.runner.calls, [[TMUX, "kill-pane", "-t", PANE]])

    def test_should_close_when_the_watcher_already_moved_the_report_to_done(self):
        self.store(section="done")
        self.close()
        self.assertEqual(len(self.runner.calls), 1)

    def test_should_keep_the_tab_open_until_the_session_reports(self):
        self.store(report=False)
        with self.assertRaisesRegex(close_tab.CloseError, "has not reported yet"):
            self.close()
        self.assertEqual(self.runner.calls, [])

    def test_should_refuse_a_tab_from_an_earlier_dispatch(self):
        self.store(dispatch="other999")
        with self.assertRaisesRegex(close_tab.CloseError, "not the one in flight"):
            self.close()
        self.assertEqual(self.runner.calls, [])

    def test_should_refuse_when_the_pr_is_not_in_the_ledger(self):
        with self.assertRaisesRegex(close_tab.CloseError, "no session d1d2d3d4 for acme/widgets#7"):
            self.close()

    def test_should_refuse_outside_a_tmux_pane(self):
        self.store()
        for env in ({}, {"TMUX_PANE": ""}, {"TMUX_PANE": "12"}, {"TMUX_PANE": "%1; rm -rf /"}):
            with self.assertRaisesRegex(close_tab.CloseError, "not running inside a tmux pane", msg=repr(env)):
                self.close(env=env)
        self.assertEqual(self.runner.calls, [])

    def test_should_fail_when_tmux_is_missing(self):
        self.store()
        with self.assertRaisesRegex(close_tab.CloseError, "tmux was not found on PATH"):
            self.close(which=lambda name: None)

    def test_should_report_a_tmux_failure(self):
        self.store()
        self.runner = Runner(returncode=1, stderr="can't find pane: %12\n")
        with self.assertRaisesRegex(close_tab.CloseError, "kill-pane failed: can't find pane: %12$"):
            self.close()
        self.runner = Runner(error=subprocess.TimeoutExpired("tmux", 30))
        with self.assertRaisesRegex(close_tab.CloseError, "tmux could not be run"):
            self.close()

    def test_cli_should_print_the_error_and_exit_1(self):
        self.store(report=False)
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"TMUX_PANE": PANE}), contextlib.redirect_stdout(out):
            code = close_tab.main(["--ledger", self.path, "--repo", REPO, "--pr", "7", "--dispatch", DISPATCH])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue()),
                         {"error": "acme/widgets#7 has not reported yet; run report.py first"})


if __name__ == "__main__":
    unittest.main()
