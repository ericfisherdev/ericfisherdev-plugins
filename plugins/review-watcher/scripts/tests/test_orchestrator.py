import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config  # noqa: E402
import gh_client  # noqa: E402
import launcher  # noqa: E402
import ledger  # noqa: E402
import orchestrator  # noqa: E402
import report  # noqa: E402
import repos  # noqa: E402
import review_poll_scan  # noqa: E402
import workdir  # noqa: E402
from fake_gh import FakeGh  # noqa: E402
from launcher import LaunchError, LaunchTimeout, claude_argv  # noqa: E402

ME = "me-dev"
REPO = "acme/widgets"
KEY = "acme/widgets#1"
SESSION = "Rev PR#1 acme/widgets"
PROMPT = "review-acme_widgets-1.md"
WATCHED = ["acme/widgets", "acme/gadgets"]
CFG = {"reviewCommand": "/team-review {repo} {pr}", "afterReportCommand": None, "model": None, "effort": None,
       "staleMinutes": 45, "intervalSeconds": 300, "launcher": "auto", "reposRoot": "C:/Users/x/GitHub",
       "noWorktreeDir": "clone", "closeTabWhenDone": False}


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeBackend:
    def __init__(self, lock_path, error=None):
        self.lock_path = lock_path
        self.error = error
        self.calls = []
        self.pins = []

    def open_tab(self, title, cwd, argv, keep_open=True, pin_title=True):
        assert not os.path.exists(self.lock_path), "open_tab ran while the ledger lock was held"
        if self.error:
            raise self.error
        self.calls.append((title, cwd, argv))
        self.pins.append(pin_title)


class FakeGit:
    """An injected git runner: records calls, asserts the ledger lock is free, never runs git."""

    def __init__(self, lock_path, result=(128, "", "fatal: not a git repository")):
        self.lock_path = lock_path
        self.result = result
        self.calls = []

    def __call__(self, args):
        assert not os.path.exists(self.lock_path), "git ran while the ledger lock was held"
        self.calls.append(list(args))
        return self.result


def locked_gh(fake, lock_path):
    """Wrap a FakeGh runner so a gh call made while the ledger lock is held fails the test."""
    def runner(args, input=None):
        assert not os.path.exists(lock_path), "gh ran while the ledger lock was held"
        return fake(args, input=input)
    return runner


class FakeEvents:
    def __init__(self, lock_path):
        self.lock_path = lock_path
        self.emitted = []
        self.notes = []

    def emit(self, event_type, **fields):
        assert not os.path.exists(self.lock_path), "emit ran while the ledger lock was held"
        self.emitted.append((event_type, fields))

    def note(self, text):
        self.notes.append(text)

    def start_note(self):
        self.notes.append("start")

    def types(self):
        return [t for t, _ in self.emitted]


class Scans:
    """An injected scan runner. `review` is a result, an exception to raise, or a callable taking the args."""

    def __init__(self):
        self.review = review_result([], [])
        self.calls = []

    def __call__(self, script, args):
        self.calls.append((script, args))
        result = self.review
        if callable(result) and not isinstance(result, Exception):
            result = result(args)
        if isinstance(result, Exception):
            raise result
        return result

    def scanned_repos(self, index=-1):
        args = self.calls[index][1]
        return [args[i + 1] for i, arg in enumerate(args) if arg == "--repo"]


def review_new(repo=REPO, pr=1, activity_at="2026-10-30T08:00:00Z", trigger="requested", requester="alice"):
    return {"repo": repo, "pr": pr, "title": "t", "author": "bob", "requester": requester,
            "requested_at": activity_at, "url": f"https://github.com/{repo}/pull/{pr}",
            "last_reply_at": "", "activity_at": activity_at, "trigger": trigger}


def review_result(new, pending):
    return {"checked_at": "x", "pending_keys": pending, "new": new, "truncated": False}


class OrchestratorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.clock = Clock()
        self.scans = Scans()
        self.watched = list(WATCHED)
        self.repos_source = lambda: list(self.watched)
        self.make()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, cfg=None, dry_run=False, backend_error=None, gh=None, git=None, repos_source=None):
        lock = str(self.state / "ledger.json.lock")
        self.backend = FakeBackend(lock, backend_error)
        self.events = FakeEvents(lock)
        if repos_source is not None:
            self.repos_source = repos_source
        self.ctx = orchestrator.Context(dict(CFG, **(cfg or {})), self.state, ME, self.backend, self.events,
                                        self.repos_source, scan=self.scans, clock=self.clock, dry_run=dry_run,
                                        gh=gh, git=git or FakeGit(lock))

    def seed(self, fn):
        with ledger.update(self.ctx.ledger_path) as data:
            fn(data)

    def data(self):
        return ledger.read(self.ctx.ledger_path)

    def review_entry(self, **extra):
        entry = {"session": SESSION, "repo": REPO, "pr": 1, "url": "u", "title": "t",
                 "activity_at": "2026-10-30T08:00:00Z", "started_at": self.clock.t, "follow_up": False,
                 "stale_notified_at": None}
        return dict(entry, **extra)

    def report(self, outcome="posted", head="abcdef1234567"):
        return {"outcome": outcome, "head_sha": head, "finished_at": "2026-10-30T09:00:00Z"}

    def write_prompt(self, name):
        prompt = self.state / "prompts" / name
        prompt.parent.mkdir(parents=True, exist_ok=True)
        prompt.write_text("x", encoding="utf-8")
        return prompt

    # --- dispatch ----------------------------------------------------------------------------

    def test_should_dispatch_a_new_review_request(self):
        self.scans.review = review_result([review_new()], [KEY])
        self.assertEqual(orchestrator.tick(self.ctx), 1)
        self.assertEqual(len(self.backend.calls), 1)
        title, cwd, argv = self.backend.calls[0]
        prompt = self.state / "prompts" / PROMPT
        self.assertEqual((title, cwd), (SESSION, "C:/Users/x/GitHub"))
        self.assertEqual(argv, claude_argv(SESSION, prompt.as_posix(), None, None))
        self.assertEqual(self.backend.pins, [False])
        data = self.data()
        self.assertEqual(data["seen"], {KEY: "2026-10-30T08:00:00Z"})
        entry = data["active"][KEY]
        self.assertEqual((entry["session"], entry["repo"], entry["activity_at"], entry["follow_up"]),
                         (SESSION, REPO, "2026-10-30T08:00:00Z", False))
        text = prompt.read_text(encoding="utf-8")
        self.assertIn("Run `/team-review acme/widgets 1` now.", text)
        report_script = orchestrator.SCRIPTS.as_posix() + "/report.py"
        self.assertTrue(os.path.isabs(report_script))
        self.assertIn(f'python3 "{report_script}" --ledger "{Path(self.ctx.ledger_path).as_posix()}" '
                      f'--repo acme/widgets --pr 1 --session "{SESSION}"', text)
        self.assertNotIn("--kind", text)
        self.assertIn("--outcome <posted|skipped|no-op|failed>", text)
        self.assertIn("gh pr view 1 -R acme/widgets --json headRefOid", text)
        for outcome in report.OUTCOMES:
            self.assertIn(f"\n- {outcome}: ", text)
        self.assertNotIn("pushed", text)
        self.assertNotIn("last action", text)
        self.assertEqual(self.events.emitted[0][0], "dispatched")
        self.assertEqual(self.events.emitted[0][1]["summary"], "review requested by alice")
        self.assertEqual(self.events.emitted[0][1]["repo"], REPO)

    def test_should_describe_a_reply_trigger(self):
        self.scans.review = review_result([review_new(trigger="reply")], [KEY])
        orchestrator.tick(self.ctx)
        self.assertEqual(self.events.emitted[0][1]["summary"], "the author replied to your review")

    def test_should_end_the_prompt_with_the_after_report_command_when_set(self):
        self.make(cfg={"afterReportCommand": "/sessions close --self --tab-close"})
        self.scans.review = review_result([review_new()], [KEY])
        self.assertEqual(orchestrator.tick(self.ctx), 1)
        text = (self.state / "prompts" / PROMPT).read_text(encoding="utf-8")
        after = text.index("`/sessions close --self --tab-close` as your last action")
        self.assertGreater(after, text.index("report.py"))
        self.assertGreater(after, text.index("headRefOid"))

    def test_should_end_the_prompt_with_the_close_tab_step_when_enabled(self):
        self.make(cfg={"closeTabWhenDone": True, "afterReportCommand": "/done"})
        self.scans.review = review_result([review_new()], [KEY])
        self.assertEqual(orchestrator.tick(self.ctx), 1)
        text = (self.state / "prompts" / PROMPT).read_text(encoding="utf-8")
        dispatch_id = self.data()["active"][KEY]["dispatch"]
        close = text.index("close_tab.py")
        self.assertIn(f"/close_tab.py\" --ledger \"{Path(self.ctx.ledger_path).as_posix()}\" "
                      f"--repo {REPO} --pr 1 --dispatch {dispatch_id}\n", text)
        self.assertGreater(close, text.index("report.py"))
        self.assertGreater(close, text.index("`/done` as your last action"))

    def test_should_leave_the_close_tab_step_out_by_default(self):
        self.scans.review = review_result([review_new()], [KEY])
        orchestrator.tick(self.ctx)
        self.assertNotIn("close_tab.py", (self.state / "prompts" / PROMPT).read_text(encoding="utf-8"))

    def test_should_fill_placeholders_in_the_after_report_command(self):
        self.make(cfg={"afterReportCommand": "/done {repo} {pr}"})
        self.scans.review = review_result([review_new()], [KEY])
        orchestrator.tick(self.ctx)
        text = (self.state / "prompts" / PROMPT).read_text(encoding="utf-8")
        self.assertIn("`/done acme/widgets 1` as your last action", text)

    def test_should_keep_same_named_repos_of_different_owners_apart(self):
        self.watched = ["acme/widgets", "other/widgets"]
        self.scans.review = review_result([review_new(), review_new(repo="other/widgets")],
                                          [KEY, "other/widgets#1"])
        orchestrator.tick(self.ctx)
        self.assertEqual([c[0] for c in self.backend.calls], [SESSION, "Rev PR#1 other/widgets"])
        self.assertEqual(sorted(self.data()["active"]), [KEY, "other/widgets#1"])
        prompts = sorted(p.name for p in (self.state / "prompts").iterdir())
        self.assertEqual(prompts, [PROMPT, "review-other_widgets-1.md"])
        self.assertIn("Run `/team-review other/widgets 1` now.",
                      (self.state / "prompts" / "review-other_widgets-1.md").read_text(encoding="utf-8"))

    def test_should_mark_follow_up_without_a_second_tab_while_a_review_is_active(self):
        self.seed(lambda d: d["active"].update({KEY: self.review_entry()}))
        self.scans.review = review_result([review_new(activity_at="2026-10-30T09:30:00Z")], [KEY])
        orchestrator.tick(self.ctx)
        self.assertEqual(self.backend.calls, [])
        data = self.data()
        self.assertTrue(data["active"][KEY]["follow_up"])
        self.assertEqual(data["seen"][KEY], "2026-10-30T09:30:00Z")

    def test_should_skip_a_review_item_no_newer_than_the_ledgers_seen(self):
        def setup(d):
            d["seen"][KEY] = "2026-10-30T09:00:00Z"
            d["done"][KEY] = self.review_entry(activity_at="2026-10-30T09:00:00Z")
        self.seed(setup)
        self.scans.review = review_result([review_new(activity_at="2026-10-30T08:00:00Z")], [KEY])
        orchestrator.tick(self.ctx)
        self.assertEqual(self.backend.calls, [])
        data = self.data()
        self.assertEqual(data["seen"][KEY], "2026-10-30T09:00:00Z")
        self.assertEqual(data["active"], {})

    def test_should_fold_a_review_report_and_dispatch_the_follow_up_it_missed(self):
        def setup(d):
            d["active"][KEY] = self.review_entry(report=self.report())
            d["seen"][KEY] = "2026-10-30T09:30:00Z"
        self.seed(setup)
        orchestrator.tick(self.ctx)
        self.assertEqual(self.events.types(), ["finished", "follow-up", "dispatched"])
        finished = self.events.emitted[0][1]
        self.assertEqual(finished["summary"], f"{SESSION}: posted, head abcdef1")
        self.assertNotIn("result", finished)
        data = self.data()
        self.assertIn(KEY, data["done"])
        self.assertEqual(data["active"][KEY]["activity_at"], "2026-10-30T09:30:00Z")
        self.assertEqual(len(self.backend.calls), 1)

    def test_should_not_dispatch_after_a_review_report_with_no_newer_activity(self):
        def setup(d):
            d["active"][KEY] = self.review_entry(report=self.report("skipped"))
            d["seen"][KEY] = "2026-10-30T08:00:00Z"
        self.seed(setup)
        self.scans.review = review_result([], [KEY])
        orchestrator.tick(self.ctx)
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.events.types(), ["finished"])
        self.assertEqual(self.events.emitted[0][1]["summary"], f"{SESSION}: skipped, head abcdef1")
        self.assertEqual(self.data()["active"], {})

    def test_should_delete_the_prompt_file_when_its_report_is_folded(self):
        prompt = self.write_prompt(PROMPT)
        other = self.write_prompt("review-acme_widgets-2.md")
        self.seed(lambda d: d["active"].update({
            KEY: self.review_entry(report=self.report()),
            "acme/widgets#2": self.review_entry(pr=2, session="Rev PR#2 acme/widgets")}))
        orchestrator.tick(self.ctx)
        self.assertFalse(prompt.exists())
        self.assertTrue(other.exists())

    def test_should_keep_the_prompt_file_of_a_folded_report_in_dry_run(self):
        prompt = self.write_prompt(PROMPT)
        self.seed(lambda d: d["active"].update({KEY: self.review_entry(report=self.report())}))
        self.ctx.dry_run = True
        orchestrator.tick(self.ctx)
        self.assertTrue(prompt.exists())

    def test_should_prune_seen_and_done_but_keep_active_keys(self):
        def setup(d):
            d["seen"].update({"acme/a#1": "x", "acme/b#2": "x", "acme/c#3": "x"})
            d["done"].update({"acme/a#1": {}, "acme/c#3": {}})
            d["active"]["acme/b#2"] = self.review_entry(repo="acme/b", pr=2)
        self.seed(setup)
        self.scans.review = review_result([], ["acme/c#3"])
        orchestrator.tick(self.ctx)
        data = self.data()
        self.assertEqual(sorted(data["seen"]), ["acme/b#2", "acme/c#3"])
        self.assertEqual(sorted(data["done"]), ["acme/c#3"])

    def test_should_not_prune_from_truncated_scans(self):
        def setup(d):
            d["seen"]["acme/a#1"] = "x"
            d["done"]["acme/a#1"] = {}
        self.seed(setup)
        self.scans.review = dict(review_result([], []), truncated=True)
        orchestrator.tick(self.ctx)
        data = self.data()
        self.assertEqual(data["seen"], {"acme/a#1": "x"})
        self.assertIn("acme/a#1", data["done"])
        self.assertTrue(any("WARNING: a search was truncated" in n for n in self.events.notes))

    def test_should_notify_a_stale_session_once_and_keep_it_active(self):
        self.seed(lambda d: d["active"].update({KEY: self.review_entry(started_at=self.clock.t - 50 * 60)}))
        orchestrator.tick(self.ctx)
        orchestrator.tick(self.ctx)
        stale = [f for t, f in self.events.emitted if t == "stale-session"]
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["idle_minutes"], 50)
        self.assertEqual(stale[0]["session"], SESSION)
        entry = self.data()["active"][KEY]
        self.assertEqual(entry["stale_notified_at"], self.clock.t)
        self.assertEqual(self.data()["done"], {})
        self.assertTrue(any(n.endswith("1 in flight, 1 stale") for n in self.events.notes))

    # --- watched repositories ----------------------------------------------------------------

    def test_should_pass_the_ledger_me_and_every_watched_repo_to_the_scan(self):
        orchestrator.tick(self.ctx)
        self.assertEqual(self.scans.calls, [("review_poll_scan.py", [
            "--state", self.ctx.ledger_path, "--me", ME, "--repo", "acme/widgets", "--repo", "acme/gadgets"])])

    def test_should_read_the_watched_repos_from_the_source_on_every_tick(self):
        reads = []

        def source():
            reads.append(1)
            return list(self.watched)

        self.make(repos_source=source)
        orchestrator.tick(self.ctx)
        orchestrator.tick(self.ctx)
        self.assertEqual(len(reads), 2)

    def test_should_scan_a_repo_added_to_the_file_between_two_ticks(self):
        path = self.state / repos.FILE_NAME
        repos.write_repos(path, ["acme/widgets"])
        self.make(repos_source=orchestrator.file_repos_source(path))

        def scan(args):
            new = [review_new(repo="acme/gadgets", pr=5)] if "acme/gadgets" in args else []
            return review_result(new, [f"{r['repo']}#{r['pr']}" for r in new])

        self.scans.review = scan
        orchestrator.tick(self.ctx)
        self.assertEqual(self.scans.scanned_repos(), ["acme/widgets"])
        self.assertEqual(self.backend.calls, [])
        repos.add(path, ["acme/gadgets"], canonical=lambda name: name)
        orchestrator.tick(self.ctx)
        self.assertEqual(self.scans.scanned_repos(), ["acme/gadgets", "acme/widgets"])
        self.assertEqual([c[0] for c in self.backend.calls], ["Rev PR#5 acme/gadgets"])
        self.assertIn("acme/gadgets#5", self.data()["active"])

    def test_should_stop_scanning_a_repo_removed_from_the_file_between_two_ticks(self):
        path = self.state / repos.FILE_NAME
        repos.write_repos(path, ["acme/widgets", "acme/gadgets"])
        self.make(repos_source=orchestrator.file_repos_source(path))
        orchestrator.tick(self.ctx)
        self.assertEqual(self.scans.scanned_repos(), ["acme/gadgets", "acme/widgets"])
        repos.remove(path, ["acme/gadgets"])
        orchestrator.tick(self.ctx)
        self.assertEqual(self.scans.scanned_repos(), ["acme/widgets"])

    def seed_history(self):
        def setup(d):
            d["seen"].update({KEY: "x", "acme/gadgets#2": "y"})
            d["done"].update({KEY: {}, "acme/gadgets#2": {}})
        self.seed(setup)
        return self.data()

    def assert_skipped_without_pruning(self, before, note):
        self.assertEqual(self.scans.calls, [])
        self.assertEqual(self.data(), before)
        self.assertTrue(any(note in n and "skipping the scan this tick" in n.lower() for n in self.events.notes),
                        self.events.notes)
        self.assertTrue(any(n.startswith("tick: 0 watched repo(s)") for n in self.events.notes), self.events.notes)

    def test_should_skip_the_scan_and_keep_the_ledger_when_no_repo_is_watched(self):
        before = self.seed_history()
        self.watched = []
        self.assertEqual(orchestrator.tick(self.ctx), 1)
        self.assert_skipped_without_pruning(before, "no watched repositories")
        self.assertTrue(any("/review-watcher:watch owner/name" in n for n in self.events.notes))

    def test_should_skip_the_scan_and_keep_the_ledger_when_the_repos_file_is_missing(self):
        before = self.seed_history()
        self.make(repos_source=orchestrator.file_repos_source(self.state / "missing" / repos.FILE_NAME))
        orchestrator.tick(self.ctx)
        self.assert_skipped_without_pruning(before, "no watched repositories")

    def test_should_skip_the_scan_and_keep_the_ledger_when_the_repos_file_is_empty(self):
        before = self.seed_history()
        path = self.state / repos.FILE_NAME
        path.write_text('{"repos": []}', encoding="utf-8")
        self.make(repos_source=orchestrator.file_repos_source(path))
        orchestrator.tick(self.ctx)
        self.assert_skipped_without_pruning(before, "no watched repositories")

    def test_should_skip_the_scan_and_keep_the_ledger_when_the_repos_file_is_bad(self):
        path = self.state / repos.FILE_NAME
        for text in ("{broken", '{"repos": "acme/widgets"}', '{"repos": ["widgets"]}', "[]"):
            self.tearDown()
            self.setUp()
            before = self.seed_history()
            path = self.state / repos.FILE_NAME
            path.write_text(text, encoding="utf-8")
            self.make(repos_source=orchestrator.file_repos_source(path))
            self.assertEqual(orchestrator.tick(self.ctx), 1, text)
            self.assert_skipped_without_pruning(before, "watched repositories unreadable")
            self.assertTrue(any(str(path) in n for n in self.events.notes), text)

    def test_should_resume_scanning_once_the_repos_file_is_fixed(self):
        path = self.state / repos.FILE_NAME
        path.write_text("{broken", encoding="utf-8")
        self.make(repos_source=orchestrator.file_repos_source(path))
        orchestrator.tick(self.ctx)
        self.assertEqual(self.scans.calls, [])
        repos.write_repos(path, ["acme/widgets"])
        self.scans.review = review_result([review_new()], [KEY])
        orchestrator.tick(self.ctx)
        self.assertEqual(self.scans.scanned_repos(), ["acme/widgets"])
        self.assertEqual(len(self.backend.calls), 1)

    def test_should_still_fold_reports_while_no_repo_is_watched(self):
        def setup(d):
            d["active"][KEY] = self.review_entry(report=self.report())
            d["seen"][KEY] = "2026-10-30T09:30:00Z"
        self.seed(setup)
        self.watched = []
        orchestrator.tick(self.ctx)
        self.assertEqual(self.events.types(), ["finished", "follow-up", "dispatched"])
        self.assertEqual(self.scans.calls, [])
        self.assertIn(KEY, self.data()["done"])

    def test_should_summarise_each_tick(self):
        self.scans.review = review_result([review_new()], [KEY])
        orchestrator.tick(self.ctx)
        self.assertEqual(self.events.notes[-1], "tick: 2 watched repo(s), 1 new review request(s), 1 in flight, 0 stale")

    # --- failures ----------------------------------------------------------------------------

    def test_should_double_the_wait_after_a_rate_limit_and_keep_the_ledger(self):
        before = self.seed_history()
        self.scans.review = gh_client.RateLimited("slow down")
        self.assertEqual(orchestrator.tick(self.ctx), 2)
        self.assertEqual([c[0] for c in self.scans.calls], ["review_poll_scan.py"])
        self.assertEqual(self.data(), before)
        self.assertTrue(any("rate limited by GitHub" in n for n in self.events.notes))
        self.scans.review = orchestrator.ScanFailed("boom")
        self.assertEqual(orchestrator.tick(self.ctx), 1)
        self.assertTrue(any("review scan failed: boom" in n for n in self.events.notes))
        self.assertEqual(self.data(), before)

    def test_should_raise_when_the_ledger_is_unreadable(self):
        self.scans.review = orchestrator.Fatal("state file at x is not valid JSON")
        with self.assertRaises(orchestrator.Fatal):
            orchestrator.tick(self.ctx)

    def test_should_roll_back_active_and_seen_when_the_tab_cannot_open(self):
        self.make(backend_error=LaunchError("tmux failed"))
        self.scans.review = review_result([review_new()], [KEY])
        orchestrator.tick(self.ctx)
        data = self.data()
        self.assertEqual(data["active"], {})
        self.assertEqual(data["seen"], {})
        self.assertNotIn("dispatched", self.events.types())
        self.assertTrue(any("could not open a tab for acme/widgets#1: tmux failed" in n for n in self.events.notes))

    def test_should_keep_the_active_entry_when_the_tab_launch_times_out(self):
        self.make(backend_error=LaunchTimeout("tmux did not exit within 30s"))
        self.scans.review = review_result([review_new()], [KEY])
        orchestrator.tick(self.ctx)
        data = self.data()
        self.assertIn(KEY, data["active"])
        self.assertIn(KEY, data["seen"])
        self.assertIn("dispatched", self.events.types())
        self.assertTrue(any(f"keeping {KEY} active" in n for n in self.events.notes))
        # A second tick must not open another tab for the same PR.
        self.make()
        self.scans.review = review_result([review_new()], [KEY])
        orchestrator.tick(self.ctx)
        self.assertEqual(self.backend.calls, [])

    def test_should_retry_a_review_follow_up_whose_tab_could_not_open(self):
        def setup(d):
            d["active"][KEY] = self.review_entry(report=self.report())
            d["seen"][KEY] = "2026-10-30T09:30:00Z"
        self.seed(setup)
        self.make(backend_error=LaunchError("tmux failed"))
        # GitHub removed the request when the review was submitted, so the scan no longer lists it.
        self.scans.review = review_result([], [])
        orchestrator.tick(self.ctx)
        data = self.data()
        self.assertEqual(data["active"], {})
        self.assertEqual(data["done"][KEY]["follow_up_activity"], "2026-10-30T09:30:00Z")
        self.make()
        orchestrator.tick(self.ctx)
        self.assertEqual(len(self.backend.calls), 1)
        data = self.data()
        self.assertEqual(data["active"][KEY]["activity_at"], "2026-10-30T09:30:00Z")
        self.assertNotIn("follow_up_activity", data["done"][KEY])

    def test_should_keep_a_review_follow_up_when_interrupted_before_the_tab_launch(self):
        def setup(d):
            d["active"][KEY] = self.review_entry(report=self.report())
            d["seen"][KEY] = "2026-10-30T09:30:00Z"
        self.seed(setup)
        with mock.patch.object(orchestrator, "working_dir", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                orchestrator.tick(self.ctx)
        self.assertEqual(self.data()["done"][KEY]["follow_up_activity"], "2026-10-30T09:30:00Z")
        orchestrator.tick(self.ctx)
        self.assertEqual(len(self.backend.calls), 1)

    def test_should_put_the_dispatch_id_in_the_report_command(self):
        self.scans.review = review_result([review_new()], [KEY])
        orchestrator.tick(self.ctx)
        dispatch_id = self.data()["active"][KEY]["dispatch"]
        self.assertRegex(dispatch_id, r"^[0-9a-f]{8}$")
        text = (self.state / "prompts" / PROMPT).read_text(encoding="utf-8")
        self.assertIn(f'--session "{SESSION}" --dispatch {dispatch_id} ', text)

    def test_should_leave_the_ledger_untouched_and_open_no_tab_in_a_dry_run(self):
        self.seed(lambda d: d["seen"].update({"acme/old#1": "x"}))
        before = Path(self.ctx.ledger_path).read_bytes()
        self.make(dry_run=True)
        self.scans.review = review_result([review_new()], [KEY])
        orchestrator.tick(self.ctx)
        self.assertEqual(Path(self.ctx.ledger_path).read_bytes(), before)
        self.assertEqual(self.backend.calls, [])
        self.assertFalse((self.state / "prompts").exists())
        self.assertEqual(len([n for n in self.events.notes if n.startswith("would dispatch")]), 1)

    # --- working directory -------------------------------------------------------------------

    def layout(self, git_dir=True):
        """A real hub with a widgets clone, plus an unrelated directory for linked worktrees."""
        root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, str(root), True)
        self.hub = root / "repos"
        self.main = self.hub / "widgets"
        (self.main / ".git" if git_dir else self.main).mkdir(parents=True)
        self.wt = root / "elsewhere" / "wt-x"
        self.wt.mkdir(parents=True)
        return root

    def registry(self, *linked):
        records = [(self.main.as_posix(), "main")] + list(linked)
        return "".join(f"worktree {path}\0branch refs/heads/{branch}\0\0" for path, branch in records)

    def setup_dispatch(self, git_out, pr_view=None, cfg=None, git_rc=0, git_err="", gh_runner=None, repo=REPO):
        """Rebuild ctx with an injected git and gh, then queue one review request for the repo."""
        lock = str(self.state / "ledger.json.lock")
        self.fake_gh = FakeGh()
        if pr_view is not None:
            self.fake_gh.on("pr view", pr_view)
        self.git = FakeGit(lock, (git_rc, git_out, git_err))
        self.gh_client = gh_client.GhClient(runner=gh_runner or locked_gh(self.fake_gh, lock))
        self.make(cfg=dict(cfg or {}, reposRoot=str(self.hub)), git=self.git, gh=self.gh_client)
        self.scans.review = review_result([review_new(repo=repo)], [f"{repo}#1"])

    def head(self, branch="feature/x", cross=False):
        return {"headRefName": branch, "isCrossRepository": cross}

    def opened_in(self):
        self.assertEqual(len(self.backend.calls), 1)
        cwd = self.backend.calls[0][1]
        self.assertEqual(self.events.emitted[0][0], "dispatched")
        self.assertEqual(self.events.emitted[0][1]["cwd"], cwd)
        return cwd

    def test_should_open_the_tab_in_the_worktree_on_the_pr_branch(self):
        self.layout()
        self.setup_dispatch(self.registry((self.wt.as_posix(), "feature/x")), self.head())
        orchestrator.tick(self.ctx)
        self.assertEqual(self.opened_in(), config.native_path(self.wt.as_posix()))
        self.assertEqual(self.fake_gh.count("pr view"), 1)
        self.assertEqual(self.fake_gh.calls[0][0], "pr view 1 -R acme/widgets --json headRefName,isCrossRepository")
        self.assertEqual(self.git.calls, [["-C", os.path.join(str(self.hub), "widgets"),
                                           "worktree", "list", "--porcelain", "-z"]])
        self.assertFalse(any("opening in" in n for n in self.events.notes))

    def test_should_skip_a_registered_worktree_whose_directory_is_gone(self):
        self.layout()
        gone = self.wt.parent / "gone"
        self.setup_dispatch(self.registry((gone.as_posix(), "feature/x")), self.head())
        orchestrator.tick(self.ctx)
        self.assertEqual(self.opened_in(), str(self.main))
        self.assertFalse(any("opening in" in n for n in self.events.notes))

    def test_should_open_in_the_clone_when_no_worktree_has_the_branch(self):
        self.layout()
        detached = "worktree %s\0HEAD abc\0detached\0\0" % (self.wt.parent / "d").as_posix()
        self.setup_dispatch(self.registry((self.wt.as_posix(), "other")) + detached, self.head())
        orchestrator.tick(self.ctx)
        self.assertEqual(self.opened_in(), str(self.main))

    def test_should_open_in_the_clone_with_a_note_when_gh_fails(self):
        self.layout()
        self.setup_dispatch(self.registry((self.wt.as_posix(), "feature/x")))
        self.fake_gh.on("pr view", rc=1, stderr="HTTP 500")
        orchestrator.tick(self.ctx)
        self.assertEqual(self.opened_in(), str(self.main))
        self.assertTrue(any(f"{KEY}: could not read the head branch" in n and "opening in" in n
                            for n in self.events.notes))

    def test_should_open_in_the_clone_with_a_note_when_gh_is_rate_limited(self):
        self.layout()
        self.setup_dispatch(self.registry((self.wt.as_posix(), "feature/x")))
        self.fake_gh.on("pr view", rc=1, stderr="API rate limit exceeded")
        self.assertEqual(orchestrator.tick(self.ctx), 1)
        self.assertEqual(self.opened_in(), str(self.main))
        self.assertTrue(any("could not read the head branch" in n for n in self.events.notes))

    def test_should_open_in_the_clone_when_the_gh_runner_raises_an_os_error(self):
        self.layout()

        def runner(args, input=None):
            raise PermissionError("denied")

        self.setup_dispatch(self.registry((self.wt.as_posix(), "feature/x")), gh_runner=runner)
        orchestrator.tick(self.ctx)
        self.assertEqual(self.opened_in(), str(self.main))
        self.assertTrue(any("denied" in n for n in self.events.notes))

    def test_should_not_match_a_fork_pr_to_a_same_named_local_branch(self):
        self.layout()
        self.setup_dispatch(self.registry((self.wt.as_posix(), "feature/x")), self.head(cross=True))
        orchestrator.tick(self.ctx)
        self.assertEqual(self.opened_in(), str(self.main))

    def test_should_open_in_the_clone_with_a_note_and_no_gh_call_when_git_fails(self):
        self.layout()
        self.setup_dispatch("", self.head(), git_rc=128, git_err="fatal: dubious ownership")
        orchestrator.tick(self.ctx)
        self.assertEqual(self.opened_in(), str(self.main))
        self.assertEqual(self.fake_gh.calls, [])
        self.assertTrue(any("git worktree list failed" in n and "dubious ownership" in n
                            for n in self.events.notes))

    def test_should_open_in_the_hub_when_the_directory_is_not_a_git_clone(self):
        self.layout(git_dir=False)
        self.setup_dispatch(self.registry((self.wt.as_posix(), "feature/x")), self.head())
        orchestrator.tick(self.ctx)
        self.assertEqual(self.opened_in(), str(self.hub))
        self.assertEqual((self.git.calls, self.fake_gh.calls), ([], []))

    def test_should_open_in_the_hub_when_there_is_no_clone(self):
        self.layout()
        self.setup_dispatch("", self.head(), repo="acme/other")
        orchestrator.tick(self.ctx)
        self.assertEqual(self.opened_in(), str(self.hub))
        self.assertEqual((self.git.calls, self.fake_gh.calls), ([], []))

    def test_should_refuse_a_repo_name_that_would_climb_out_of_the_hub(self):
        self.layout()
        self.setup_dispatch("", self.head(), repo="acme/..")
        orchestrator.tick(self.ctx)
        self.assertEqual(self.opened_in(), str(self.hub))
        self.assertEqual((self.git.calls, self.fake_gh.calls), ([], []))
        self.assertTrue(any("unsafe repo name" in n for n in self.events.notes))

    def test_should_open_in_the_clone_when_the_worktree_path_would_be_refused_by_the_launcher(self):
        root = self.layout()
        odd = root / "elsewhere" / "wt (x)"
        odd.mkdir()
        self.setup_dispatch(self.registry((odd.as_posix(), "feature/x")), self.head())
        orchestrator.tick(self.ctx)
        self.assertEqual(self.opened_in(), str(self.main))
        self.assertTrue(any("has characters the launcher refuses" in n for n in self.events.notes))
        self.assertEqual(self.data()["active"][KEY]["repo"], REPO)

    def test_should_check_the_worktree_against_the_backends_character_set(self):
        root = self.layout()
        odd = root / "elsewhere" / "wt\\x"
        odd.mkdir()
        self.setup_dispatch(self.registry((odd.as_posix(), "feature/x")), self.head())
        self.backend.safe_cwd = launcher.WSL_SAFE
        orchestrator.tick(self.ctx)
        self.assertEqual(self.opened_in(), str(self.main))
        self.assertTrue(any("has characters the launcher refuses" in n for n in self.events.notes))

    def test_should_make_no_gh_call_when_the_registry_lists_only_the_main_worktree(self):
        self.layout()
        self.setup_dispatch(self.registry(), self.head("main"))
        orchestrator.tick(self.ctx)
        self.assertEqual(self.opened_in(), str(self.main))
        self.assertEqual(self.fake_gh.count("pr view"), 0)

    def test_should_open_in_the_repos_root_when_the_setting_says_root(self):
        self.layout()
        self.setup_dispatch(self.registry((self.wt.as_posix(), "other")), self.head(),
                            cfg={"noWorktreeDir": "root"})
        orchestrator.tick(self.ctx)
        self.assertEqual(self.opened_in(), str(self.hub))
        self.assertEqual(self.fake_gh.count("pr view"), 1)

    def test_should_look_up_nothing_while_the_pr_already_has_an_active_session(self):
        self.layout()
        self.setup_dispatch(self.registry((self.wt.as_posix(), "feature/x")), self.head())
        self.seed(lambda d: d["active"].update({KEY: self.review_entry()}))
        orchestrator.tick(self.ctx)
        self.assertEqual((self.backend.calls, self.git.calls, self.fake_gh.calls), ([], [], []))

    def test_should_name_the_directory_in_a_dry_run_without_changing_anything(self):
        self.layout()
        self.setup_dispatch(self.registry((self.wt.as_posix(), "feature/x")), self.head())
        self.seed(lambda d: d["seen"].update({"acme/old#1": "x"}))
        before = Path(self.ctx.ledger_path).read_bytes()
        self.make(dry_run=True, cfg={"reposRoot": str(self.hub)}, git=self.git, gh=self.gh_client)
        orchestrator.tick(self.ctx)
        wt = config.native_path(self.wt.as_posix())
        self.assertTrue(any(n.startswith(f"would dispatch {SESSION} in " + wt) for n in self.events.notes))
        self.assertEqual(Path(self.ctx.ledger_path).read_bytes(), before)
        self.assertEqual(self.backend.calls, [])
        self.assertFalse((self.state / "prompts").exists())

    # --- run_scan ----------------------------------------------------------------------------

    def run_scan(self, rc=0, stdout="", stderr="", error=None):
        seen = {}

        def run(cmd, **kwargs):
            seen["cmd"] = cmd
            if error:
                raise error
            return subprocess.CompletedProcess(cmd, rc, stdout, stderr)

        return orchestrator.run_scan("review_poll_scan.py", ["--me", ME], run=run), seen

    def test_should_parse_the_last_line_and_run_python_in_utf8_mode(self):
        out, seen = self.run_scan(stdout='warning\n{"new": []}\n')
        self.assertEqual(out, {"new": []})
        self.assertEqual(seen["cmd"][1:3], ["-X", "utf8"])
        self.assertTrue(seen["cmd"][3].endswith("review_poll_scan.py"))
        self.assertEqual(seen["cmd"][4:], ["--me", ME])

    def test_should_raise_rate_limited_only_for_the_rate_limit_json(self):
        with self.assertRaises(gh_client.RateLimited):
            self.run_scan(rc=2, stdout='{"error":"rate_limited"}\n')
        with self.assertRaises(orchestrator.ScanFailed):
            self.run_scan(rc=2, stdout="", stderr="usage: error: the following arguments are required")

    def test_should_raise_scan_failed_for_bad_output_and_timeouts(self):
        for kwargs in ({"stdout": "not json"}, {"rc": 1, "stdout": ""}, {"stdout": "[1]"},
                       {"rc": 1, "stdout": '{"error":"gh_failed","detail":"boom"}'},
                       {"rc": 1, "stdout": '{"error":"internal","detail":"x"}'},
                       {"error": subprocess.TimeoutExpired("x", 600)}, {"error": OSError("nope")}):
            with self.assertRaises(orchestrator.ScanFailed, msg=str(kwargs)):
                self.run_scan(**kwargs)

    def test_should_raise_fatal_for_a_bad_ledger(self):
        with self.assertRaisesRegex(orchestrator.Fatal, "not valid JSON"):
            self.run_scan(rc=1, stdout='{"error":"bad_state","detail":"state file at x is not valid JSON"}')

    # --- ordering contracts ------------------------------------------------------------------

    def test_should_run_nothing_slow_while_the_ledger_lock_is_held(self):
        def setup(d):
            d["active"][KEY] = self.review_entry(report=self.report())
            d["seen"][KEY] = "2026-10-30T09:30:00Z"
        self.seed(setup)
        self.scans.review = review_result([review_new(pr=2)], [KEY, "acme/widgets#2"])
        orchestrator.tick(self.ctx)
        self.assertEqual(self.events.types(), ["finished", "follow-up", "dispatched", "dispatched"])
        self.assertEqual(len(self.backend.calls), 2)

    def test_should_not_lose_a_request_when_dispatch_is_interrupted(self):
        self.scans.review = review_result([review_new()], [KEY])
        with mock.patch.object(orchestrator, "dispatch", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                orchestrator.tick(self.ctx)
        data = self.data()
        self.assertEqual(data["seen"], {})
        self.assertEqual(data["active"], {})
        orchestrator.tick(self.ctx)
        self.assertEqual(len(self.backend.calls), 1)
        self.assertIn(KEY, self.data()["active"])

    def test_should_roll_back_a_dispatch_interrupted_before_the_tab_launch(self):
        self.scans.review = review_result([review_new()], [KEY])
        with mock.patch.object(orchestrator, "working_dir", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                orchestrator.tick(self.ctx)
        data = self.data()
        self.assertEqual(data["active"], {})
        self.assertEqual(data["seen"], {})
        self.assertEqual(self.backend.calls, [])
        orchestrator.tick(self.ctx)
        self.assertEqual(len(self.backend.calls), 1)
        self.assertIn(KEY, self.data()["active"])

    def test_should_still_raise_the_interrupt_when_the_rollback_finds_the_ledger_busy(self):
        self.scans.review = review_result([review_new()], [KEY])

        def interrupt(*_args):
            self.ctx.store = mock.Mock(side_effect=ledger.LedgerBusy("ledger is busy"))
            raise KeyboardInterrupt

        with mock.patch.object(orchestrator, "working_dir", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                orchestrator.tick(self.ctx)
        self.assertTrue(any(f"could not roll back {KEY}" in note for note in self.events.notes))

    def test_should_keep_the_active_entry_when_interrupted_during_the_tab_launch(self):
        self.make(backend_error=KeyboardInterrupt())
        self.scans.review = review_result([review_new()], [KEY])
        with self.assertRaises(KeyboardInterrupt):
            orchestrator.tick(self.ctx)
        self.assertIn(KEY, self.data()["active"])

    def test_should_not_lose_a_review_follow_up_when_interrupted_after_the_fold(self):
        def setup(d):
            d["active"][KEY] = self.review_entry(report=self.report())
            d["seen"][KEY] = "2026-10-30T09:30:00Z"
        self.seed(setup)
        with mock.patch.object(orchestrator, "flush", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                orchestrator.tick(self.ctx)
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.data()["active"], {})
        orchestrator.tick(self.ctx)
        self.assertEqual(len(self.backend.calls), 1)
        data = self.data()
        self.assertEqual(data["active"][KEY]["activity_at"], "2026-10-30T09:30:00Z")
        self.assertNotIn("follow_up_activity", data["done"].get(KEY, {}))
        orchestrator.tick(self.ctx)
        self.assertEqual(len(self.backend.calls), 1)

    def test_should_never_dispatch_a_pr_twice(self):
        self.scans.review = review_result([review_new()], [KEY])
        orchestrator.tick(self.ctx)
        orchestrator.tick(self.ctx)
        self.assertEqual(len(self.backend.calls), 1)

    # --- fold to real scan -------------------------------------------------------------------

    def real_scan(self, requested_at):
        """Route the tick's scan through review_poll_scan.scan over a fake gh, reading the real ledger."""
        gh = (FakeGh()
              .on("search prs", [{"repository": {"name": "widgets", "nameWithOwner": REPO}, "number": 1,
                                  "title": "t", "author": {"login": "bob"},
                                  "url": "https://github.com/acme/widgets/pull/1"}])
              .on_lines("issues/1/timeline", [{"event": "review_requested", "requested_reviewer": {"login": ME},
                                               "actor": {"login": "alice"}, "created_at": requested_at}])
              .on_lines("pulls/1/comments", []))
        client = gh_client.GhClient(runner=gh)
        scanned = []

        def scan(script, args):
            watched = [args[i + 1] for i, arg in enumerate(args) if arg == "--repo"]
            seen = ledger.read(args[args.index("--state") + 1])["seen"]
            scanned.append(review_poll_scan.scan(client, args[args.index("--me") + 1], seen, watched,
                                                 now=datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)))
            return scanned[-1]

        self.ctx.scan = scan
        return scanned, gh

    def test_should_see_a_folded_review_as_handled_in_the_real_scan(self):
        self.seed(lambda d: (d["active"].update({KEY: self.review_entry(report=self.report())}),
                             d["seen"].update({KEY: "2026-10-30T08:00:00Z"})))
        scanned, gh = self.real_scan("2026-10-30T08:00:00Z")
        orchestrator.tick(self.ctx)
        self.assertEqual(scanned[-1]["already_handled"], 1)
        self.assertEqual(scanned[-1]["pending_keys"], [KEY])
        self.assertEqual(self.backend.calls, [])
        self.assertIn("--repo acme/widgets --repo acme/gadgets", gh.calls[0][0])
        self.assertIn(KEY, self.data()["done"])

    def test_should_dispatch_a_re_request_after_the_fold_in_the_real_scan(self):
        self.seed(lambda d: (d["active"].update({KEY: self.review_entry(report=self.report())}),
                             d["seen"].update({KEY: "2026-10-30T08:00:00Z"})))
        scanned, _gh = self.real_scan("2026-10-30T10:00:00Z")
        orchestrator.tick(self.ctx)
        self.assertEqual(scanned[-1]["actionable"], 1)
        self.assertEqual([c[0] for c in self.backend.calls], [SESSION])
        self.assertEqual(self.data()["seen"][KEY], "2026-10-30T10:00:00Z")

    # --- heartbeat ---------------------------------------------------------------------------

    def test_should_heartbeat_after_every_dispatch(self):
        beats = []
        self.ctx.heartbeat = lambda: beats.append(len(self.backend.calls))
        self.scans.review = review_result([review_new(pr=n) for n in (1, 2, 3)],
                                          ["acme/widgets#1", "acme/widgets#2", "acme/widgets#3"])
        orchestrator.tick(self.ctx)
        self.assertEqual(len(self.backend.calls), 3)
        for dispatched in (1, 2, 3):
            self.assertIn(dispatched, beats)

    def test_should_heartbeat_after_every_folded_event(self):
        beats = []
        self.ctx.heartbeat = lambda: beats.append(len(self.events.emitted))
        self.seed(lambda d: d["active"].update({
            KEY: self.review_entry(report=self.report()),
            "acme/widgets#2": self.review_entry(pr=2, session="Rev PR#2 acme/widgets", report=self.report())}))
        orchestrator.tick(self.ctx)
        self.assertEqual(self.events.types()[:2], ["finished", "finished"])
        self.assertIn(1, beats)
        self.assertIn(2, beats)

    def test_should_keep_the_poller_stale_window_longer_than_a_scan_plus_a_dispatch(self):
        slowest_step = ledger.SCAN_TIMEOUT_SECONDS + launcher.RUN_TIMEOUT_SECONDS + gh_client.GH_TIMEOUT_SECONDS
        self.assertGreater(ledger.POLLER_STALE_SECONDS, slowest_step)
        one_dispatch = (2 * gh_client.GH_TIMEOUT_SECONDS + workdir.GIT_TIMEOUT_SECONDS
                        + 2 * launcher.RUN_TIMEOUT_SECONDS)
        self.assertGreater(ledger.POLLER_STALE_SECONDS, one_dispatch)


class FakeLauncher:
    name = "fake"

    def __init__(self, problems=()):
        self._problems = list(problems)
        self.opened = []
        self.pins = []

    def problems(self):
        return list(self._problems)

    def open_tab(self, title, cwd, argv, keep_open=True, pin_title=True):
        self.opened.append((title, cwd, argv))
        self.pins.append(pin_title)


class StartupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = {"CLAUDE_CONFIG_DIR": str(self.root / "cfg")}
        self.state = self.root / "cfg" / "review-watcher"
        self.repos = self.root / "repos"
        self.repos.mkdir()
        self.gh = FakeGh().on("api user", "me-dev\n")
        self.client = gh_client.GhClient(runner=self.gh)
        self.lines = []

    def tearDown(self):
        self.tmp.cleanup()

    def configure(self, watched=("acme/widgets",), **extra):
        config.set_value("review-command", "/team-review {repo} {pr}", self.env)
        config.set_value("repos-root", str(self.repos), self.env)
        for name, value in extra.items():
            config.set_value(name, value, self.env)
        if watched is not None:
            repos.write_repos(self.state / repos.FILE_NAME, list(watched))

    def cfg(self, **over):
        base = dict(CFG, reposRoot=str(self.repos))
        return dict(base, **over)

    def check(self, cfg, which=lambda name: name, backend=None, watched=("acme/widgets",), source=None):
        backend = backend or FakeLauncher()
        return orchestrator.preflight(cfg, which, self.client, lambda: backend, source or (lambda: list(watched)))

    def test_should_refuse_to_start_without_the_review_command_and_point_at_setup(self):
        result = self.check(self.cfg(reviewCommand=None))
        self.assertEqual(len(result["problems"]), 1)
        self.assertIn("missing reviewCommand", result["problems"][0])
        self.assertIn("/review-watcher:setup", result["problems"][0])
        self.assertEqual(self.check(self.cfg())["problems"], [])
        self.assertEqual(self.check(self.cfg())["me"], "me-dev")

    def test_should_refuse_to_start_when_no_repo_is_watched(self):
        result = self.check(self.cfg(), watched=())
        self.assertEqual(len(result["problems"]), 1)
        self.assertIn("no repositories are watched", result["problems"][0])
        self.assertIn("/review-watcher:watch owner/name", result["problems"][0])

    def test_should_refuse_to_start_when_the_repos_file_is_bad(self):
        path = self.root / "repos.json"
        path.write_text('{"repos": ["widgets"]}', encoding="utf-8")
        result = self.check(self.cfg(), source=orchestrator.file_repos_source(path))
        self.assertEqual(len(result["problems"]), 1)
        self.assertIn(str(path), result["problems"][0])

    def test_should_note_the_watched_repos_the_root_and_the_launcher(self):
        result = self.check(self.cfg(), watched=("acme/gadgets", "acme/widgets"))
        self.assertEqual(result["notes"], ["watching: acme/gadgets, acme/widgets", f"repos root: {self.repos}",
                                           "launcher: fake"])

    def test_should_report_gh_the_repos_root_and_launcher_problems(self):
        result = self.check(self.cfg(reposRoot=str(self.root / "nope")), which=lambda name: None,
                            backend=FakeLauncher(["tmux was not found on PATH"]))
        text = " | ".join(result["problems"])
        self.assertIn("GitHub CLI (gh) is not installed", text)
        self.assertIn("repos root is not a directory", text)
        self.assertIn("tmux was not found", text)
        failing = gh_client.GhClient(runner=FakeGh().on("api user", rc=1, stderr="not logged in"))
        result = orchestrator.preflight(self.cfg(), lambda n: n, failing, FakeLauncher, lambda: ["acme/widgets"])
        self.assertIn("gh is not authenticated", result["problems"][0])

    def test_should_report_a_launcher_that_cannot_be_built(self):
        def broken():
            raise LaunchError("unknown launcher 'mac'")

        result = orchestrator.preflight(self.cfg(), lambda n: n, self.client, broken, lambda: ["acme/widgets"])
        self.assertEqual(result["problems"], ["unknown launcher 'mac'"])
        self.assertIsNone(result["backend"])
        self.assertNotIn("launcher: fake", result["notes"])

    def test_should_read_the_repos_file_each_time_its_source_is_called(self):
        path = self.root / "repos.json"
        source = orchestrator.file_repos_source(path)
        self.assertEqual(source(), [])
        repos.write_repos(path, ["acme/widgets"])
        self.assertEqual(source(), ["acme/widgets"])
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(repos.RepoError):
            source()

    def run_preflight(self):
        out = io.StringIO()
        with mock.patch.object(orchestrator.launcher, "detect", return_value=FakeLauncher()):
            with contextlib.redirect_stdout(out):
                code = orchestrator.main(["preflight"], env=self.env, which=lambda n: n,
                                         gh_factory=lambda: self.client)
        return code, json.loads(out.getvalue())

    def test_should_print_the_preflight_result_as_json(self):
        self.configure()
        code, out = self.run_preflight()
        self.assertEqual((code, out["ok"], out["problems"]), (0, True, []))
        self.assertIn("watching: acme/widgets", out["notes"])

    def test_should_fail_preflight_without_a_repos_file(self):
        self.configure(watched=None)
        code, out = self.run_preflight()
        self.assertEqual((code, out["ok"]), (1, False))
        self.assertTrue(any("no repositories are watched" in p for p in out["problems"]))

    def test_should_fail_preflight_for_a_corrupt_config_file(self):
        self.state.mkdir(parents=True)
        (self.state / "config.json").write_text("{broken", encoding="utf-8")
        code, out = self.run_preflight()
        self.assertEqual((code, out["ok"]), (1, False))
        self.assertIn("not valid JSON", out["problems"][0])

    def open_tab(self, *argv):
        backend = FakeLauncher()
        out = io.StringIO()
        with mock.patch.object(orchestrator.launcher, "detect", return_value=backend):
            with contextlib.redirect_stdout(out):
                code = orchestrator.main(["open-tab", *argv], env=self.env, which=lambda n: n,
                                         gh_factory=lambda: self.client)
        return code, backend, json.loads(out.getvalue())

    def test_should_open_the_watcher_tab_with_an_explicit_state_dir(self):
        self.configure()
        code, backend, out = self.open_tab("--dry-run")
        self.assertEqual(code, 0)
        title, cwd, argv = backend.opened[0]
        self.assertEqual((title, cwd), ("Review Watcher", str(self.repos)))
        self.assertEqual(backend.pins, [True])
        self.assertEqual(argv[0], "python3")
        self.assertTrue(argv[1].endswith("/orchestrator.py"))
        self.assertEqual(argv[2:4], ["run", "--state-dir"])
        self.assertEqual(argv[4], self.state.resolve().as_posix())
        self.assertEqual(argv[5:], ["--dry-run"])
        self.assertEqual(out, {"ok": True, "title": "Review Watcher", "launcher": "fake", "state_dir": str(self.state)})

    def test_should_not_open_a_tab_when_preflight_fails(self):
        code, backend, out = self.open_tab()
        self.assertEqual(code, 1)
        self.assertEqual(backend.opened, [])
        self.assertIn("/review-watcher:setup", out["problems"][0])

    def test_should_not_open_a_tab_when_no_repo_is_watched(self):
        self.configure(watched=())
        code, backend, out = self.open_tab()
        self.assertEqual(code, 1)
        self.assertEqual(backend.opened, [])
        self.assertTrue(any("no repositories are watched" in p for p in out["problems"]))

    def run_main(self, *argv, scans=None, sleep=lambda s: None):
        backend = FakeLauncher()
        args = orchestrator.build_parser().parse_args(["run", *argv])
        with mock.patch.object(orchestrator.launcher, "detect", return_value=backend):
            code = orchestrator.command_run(args, self.env, lambda n: n, lambda: self.client, "nt",
                                            out=self.lines.append, sleep=sleep, scan=scans or Scans())
        return code, backend

    def test_should_poll_once_hold_the_poller_lock_and_release_it(self):
        self.configure()
        scans = Scans()
        code, _ = self.run_main("--once", "--state-dir", str(self.state), scans=scans)
        self.assertEqual(code, 0)
        self.assertFalse((self.state / "poller.lock").exists())
        log = self.state / "watcher.log"
        self.assertTrue(log.exists())
        self.assertTrue(any(f"events go to this window and {log}" in line for line in self.lines))
        self.assertEqual(scans.scanned_repos(), ["acme/widgets"])

    def test_should_stop_when_another_watcher_takes_the_poller_lock_over(self):
        self.configure()
        scans = Scans()
        lock = str(self.state / "poller.lock")
        other = {"pid": 4242, "started_at": 1.0, "heartbeat_at": time.time()}

        def take_over(_seconds):
            Path(lock).write_text(json.dumps(other), encoding="utf-8")

        code, _ = self.run_main("--state-dir", str(self.state), scans=scans, sleep=take_over)
        self.assertEqual(code, 1)
        self.assertEqual(len(scans.calls), 1)
        self.assertTrue(any("fatal:" in line and "another watcher took over" in line for line in self.lines))
        self.assertEqual(json.loads(Path(lock).read_text(encoding="utf-8")), other)

    def test_should_refuse_to_run_when_no_repo_is_watched(self):
        self.configure(watched=())
        scans = Scans()
        code, _ = self.run_main("--once", "--state-dir", str(self.state), scans=scans)
        self.assertEqual(code, 1)
        self.assertEqual(scans.calls, [])
        self.assertTrue(any("no repositories are watched" in line for line in self.lines))
        self.assertFalse((self.state / "poller.lock").exists())

    def test_should_pick_up_a_repo_added_while_running(self):
        self.configure()
        scans = Scans()
        per_wait = config.SETTINGS["interval-seconds"][2] // orchestrator.WAIT_CHUNK_SECONDS
        slept = []

        def sleep(_seconds):
            slept.append(1)
            if len(slept) == 1:
                repos.add(self.state / repos.FILE_NAME, ["acme/gadgets"], canonical=lambda name: name)
            if len(slept) > per_wait:
                raise KeyboardInterrupt

        code, _ = self.run_main("--state-dir", str(self.state), scans=scans, sleep=sleep)
        self.assertEqual(code, 0)
        self.assertEqual([scans.scanned_repos(i) for i in range(len(scans.calls))],
                         [["acme/widgets"], ["acme/gadgets", "acme/widgets"]])

    def test_should_refuse_a_second_poller_and_leave_its_lock_alone(self):
        self.configure()
        ledger.acquire_poller(str(self.state / "poller.lock"), now=time.time(), pid=4242)
        code, _ = self.run_main("--once", "--state-dir", str(self.state))
        self.assertEqual(code, 1)
        self.assertTrue(any("another watcher (pid 4242)" in line for line in self.lines))
        self.assertTrue((self.state / "poller.lock").exists())

    def test_should_not_take_the_lock_or_write_anything_in_a_dry_run(self):
        self.configure()
        scans = Scans()
        scans.review = review_result([review_new()], [KEY])
        code, backend = self.run_main("--once", "--dry-run", "--state-dir", str(self.state), scans=scans)
        self.assertEqual(code, 0)
        self.assertFalse((self.state / "poller.lock").exists())
        self.assertFalse((self.state / "watcher.log").exists())
        self.assertFalse((self.state / "ledger.json").exists())
        self.assertEqual(backend.opened, [])
        self.assertTrue(any(f"would dispatch {SESSION}" in line for line in self.lines))

    def test_should_refuse_a_state_dir_not_named_review_watcher(self):
        self.configure()
        code, _ = self.run_main("--once", "--state-dir", str(self.root / "elsewhere"))
        self.assertEqual(code, 1)
        self.assertTrue(any("--state-dir must end in review-watcher" in line for line in self.lines))

    def test_should_point_config_at_the_parent_of_the_state_dir(self):
        env = orchestrator.config_env({"PATH": "/bin"}, self.state)
        self.assertEqual(env, {"PATH": "/bin", "CLAUDE_CONFIG_DIR": str(self.state.parent)})
        self.assertEqual(config.state_dir(env), self.state)

    def make_ctx(self, interval=100):
        self.configure()
        lock = str(self.state / "ledger.json.lock")
        self.fake_events = FakeEvents(lock)
        self.beats = []
        ctx = orchestrator.Context(dict(CFG, intervalSeconds=interval, reposRoot=str(self.repos)), self.state, ME,
                                   FakeBackend(lock), self.fake_events, lambda: ["acme/widgets"], scan=Scans(),
                                   heartbeat=lambda: self.beats.append(1))
        return ctx

    def test_should_wait_in_chunks_and_heartbeat_between_them(self):
        ctx = self.make_ctx(interval=100)
        slept = []

        def sleep(seconds):
            slept.append(seconds)
            if len(slept) == 4:
                raise KeyboardInterrupt

        with ledger.update(ctx.ledger_path) as data:
            data["active"][KEY] = {"session": SESSION, "repo": REPO, "pr": 1, "started_at": ctx.clock()}
        self.assertEqual(orchestrator.run_loop(ctx, sleep=sleep), 0)
        self.assertEqual(slept, [30, 30, 30, 10])
        # One tick heartbeats before and after its scan, then once after each completed sleep.
        self.assertEqual(len(self.beats), 2 + 3)
        self.assertIn(f"stopped; 1 session(s) still in flight: {SESSION}", self.fake_events.notes[-1])

    def test_should_double_the_wait_after_a_rate_limit(self):
        ctx = self.make_ctx(interval=60)
        ctx.scan.review = gh_client.RateLimited("slow")
        slept = []

        def sleep(seconds):
            slept.append(seconds)
            if sum(slept) >= 120:
                raise KeyboardInterrupt

        orchestrator.run_loop(ctx, sleep=sleep)
        self.assertEqual(sum(slept), 120)

    def test_should_keep_running_when_the_ledger_is_busy(self):
        ctx = self.make_ctx(interval=60)
        with mock.patch.object(orchestrator.ledger, "update", side_effect=ledger.LedgerBusy("ledger is locked")):
            self.assertEqual(orchestrator.run_loop(ctx, once=True), 0)
        self.assertTrue(any("ledger is locked; trying again next tick" in n for n in self.fake_events.notes))

    def test_should_exit_nonzero_when_the_ledger_is_unreadable(self):
        ctx = self.make_ctx()
        Path(ctx.ledger_path).write_text("{broken", encoding="utf-8")
        self.assertEqual(orchestrator.run_loop(ctx, once=True), 1)
        self.assertTrue(any(n.startswith("fatal:") for n in self.fake_events.notes))


if __name__ == "__main__":
    unittest.main()
