import contextlib
import io
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import gh_client  # noqa: E402
import review_poll_scan  # noqa: E402
from fake_gh import FakeGh  # noqa: E402

NOW = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)
ME = "me-dev"
REPOS = ["acme/widgets", "acme/gadgets"]


def search_result(*prs):
    return [
        {"repository": {"name": repo.split("/")[1], "nameWithOwner": repo}, "number": n, "title": f"PR {n}",
         "author": {"login": "author1"}, "url": f"https://github.com/{repo}/pull/{n}"}
        for repo, n in prs
    ]


def request_event(reviewer, at, actor="lead"):
    return {"event": "review_requested", "requested_reviewer": {"login": reviewer},
            "actor": {"login": actor}, "created_at": at}


def root(comment_id, user):
    return {"id": comment_id, "in_reply_to_id": None, "user": {"login": user, "type": "User"},
            "created_at": "2026-09-19T00:00:00Z"}


def reply(user, at, user_type="User", in_reply_to=1):
    return {"id": 0, "in_reply_to_id": in_reply_to, "user": {"login": user, "type": user_type}, "created_at": at}


def repo_list(count):
    return [f"acme/r{n:02d}" for n in range(count)]


def repo_flags(joined):
    """The --repo values in one joined gh call."""
    args = joined.split(" ")
    return [args[i + 1] for i, arg in enumerate(args) if arg == "--repo"]


class ReviewPollScanTest(unittest.TestCase):
    def scan(self, gh, seen=None, repos=None, limit=100):
        client = gh_client.GhClient(runner=gh)
        return review_poll_scan.scan(client, ME, seen or {}, REPOS if repos is None else repos,
                                     stale_days=10, now=NOW, limit=limit)

    def searches(self, gh):
        return [joined for joined, _ in gh.calls if joined.startswith("search prs")]

    def test_should_report_unseen_request_as_new_with_requested_trigger(self):
        gh = (FakeGh()
              .on("search prs", search_result(("acme/widgets", 10)))
              .on_lines("repos/acme/widgets/issues/10/timeline", [request_event(ME, "2026-09-21T10:00:00Z")])
              .on_lines("repos/acme/widgets/pulls/10/comments", []))
        out = self.scan(gh)
        self.assertEqual(out["pending_total"], 1)
        self.assertEqual(out["pending_keys"], ["acme/widgets#10"])
        self.assertEqual(len(out["new"]), 1)
        entry = out["new"][0]
        self.assertEqual(entry["repo"], "acme/widgets")
        self.assertEqual(entry["requester"], "lead")
        self.assertEqual(entry["activity_at"], "2026-09-21T10:00:00Z")
        self.assertEqual(entry["trigger"], "requested")
        self.assertEqual(entry["last_reply_at"], "")
        self.assertEqual(entry["url"], "https://github.com/acme/widgets/pull/10")

    def test_should_key_by_owner_and_name_so_same_named_repos_stay_apart(self):
        gh = (FakeGh()
              .on("search prs", search_result(("acme/widgets", 10), ("other/widgets", 10)))
              .on_lines("repos/acme/widgets/issues/10/timeline", [request_event(ME, "2026-09-21T10:00:00Z")])
              .on_lines("repos/other/widgets/issues/10/timeline", [request_event(ME, "2026-09-21T11:00:00Z")])
              .on_lines("comments", []))
        out = self.scan(gh, seen={"acme/widgets#10": "2026-09-21T10:00:00Z"},
                        repos=["acme/widgets", "other/widgets"])
        self.assertEqual(out["pending_keys"], ["acme/widgets#10", "other/widgets#10"])
        self.assertEqual([(e["repo"], e["pr"]) for e in out["new"]], [("other/widgets", 10)])
        self.assertEqual(out["already_handled"], 1)
        self.assertEqual(gh.count("repos/other/widgets/pulls/10/comments"), 1)

    def test_should_use_latest_request_for_me_and_ignore_other_reviewers(self):
        gh = (FakeGh()
              .on("search prs", search_result(("acme/widgets", 10)))
              .on_lines("issues/10/timeline", [
                  request_event(ME, "2026-09-20T10:00:00Z", actor="old"),
                  request_event(ME, "2026-09-21T10:00:00Z", actor="new"),
                  request_event("someone-else", "2026-09-21T11:00:00Z", actor="other"),
              ])
              .on_lines("pulls/10/comments", []))
        entry = self.scan(gh)["new"][0]
        self.assertEqual(entry["requester"], "new")
        self.assertEqual(entry["requested_at"], "2026-09-21T10:00:00Z")

    def test_should_fire_reply_trigger_when_human_reply_is_newer_than_seen(self):
        gh = (FakeGh()
              .on("search prs", search_result(("acme/widgets", 10)))
              .on_lines("issues/10/timeline", [request_event(ME, "2026-09-20T10:00:00Z")])
              .on_lines("pulls/10/comments", [
                  root(1, ME),
                  root(2, "coderabbitai[bot]"),
                  reply("author1", "2026-09-21T09:00:00Z"),
                  reply("author1", "2026-09-21T20:00:00Z", in_reply_to=2),
                  reply("coderabbitai[bot]", "2026-09-22T09:00:00Z", user_type="Bot"),
                  reply(ME, "2026-09-22T10:00:00Z"),
                  {"in_reply_to_id": None, "user": {"login": "author1", "type": "User"},
                   "created_at": "2026-09-22T11:00:00Z"},
              ]))
        out = self.scan(gh, seen={"acme/widgets#10": "2026-09-20T10:00:00Z"})
        entry = out["new"][0]
        self.assertEqual(entry["last_reply_at"], "2026-09-21T09:00:00Z")
        self.assertEqual(entry["activity_at"], "2026-09-21T09:00:00Z")
        self.assertEqual(entry["trigger"], "reply")

    def test_should_not_report_request_already_seen_at_same_activity(self):
        gh = (FakeGh()
              .on("search prs", search_result(("acme/widgets", 10)))
              .on_lines("issues/10/timeline", [request_event(ME, "2026-09-21T10:00:00Z")])
              .on_lines("pulls/10/comments", []))
        out = self.scan(gh, seen={"acme/widgets#10": "2026-09-21T10:00:00Z"})
        self.assertEqual(out["new"], [])
        self.assertEqual(out["already_handled"], 1)
        self.assertEqual(out["actionable"], 0)

    def test_should_count_stale_request_as_subset_of_pending_total(self):
        gh = (FakeGh()
              .on("search prs", search_result(("acme/widgets", 10)))
              .on_lines("issues/10/timeline", [request_event(ME, "2026-09-01T10:00:00Z")])
              .on_lines("pulls/10/comments", []))
        out = self.scan(gh)
        self.assertEqual(out["pending_total"], 1)
        self.assertEqual(out["stale_ignored"], 1)
        self.assertEqual(out["new"], [])
        self.assertEqual(out["actionable"], 0)

    def test_should_keep_request_exactly_at_stale_boundary(self):
        gh = (FakeGh()
              .on("search prs", search_result(("acme/widgets", 10), ("acme/widgets", 11)))
              .on_lines("issues/10/timeline", [request_event(ME, "2026-09-12T12:00:00Z")])
              .on_lines("issues/11/timeline", [request_event(ME, "2026-09-12T11:59:59Z")])
              .on_lines("comments", []))
        out = self.scan(gh)
        self.assertEqual([e["pr"] for e in out["new"]], [10])
        self.assertEqual(out["stale_ignored"], 1)

    def test_should_treat_team_request_without_timeline_event_as_unknown_and_not_stale(self):
        gh = (FakeGh()
              .on("search prs", search_result(("acme/gadgets", 7)))
              .on_lines("issues/7/timeline", [{"event": "review_requested", "requested_team": {"slug": "devs"},
                                               "actor": {"login": "lead"}, "created_at": "2026-01-01T00:00:00Z"}])
              .on_lines("pulls/7/comments", []))
        entry = self.scan(gh)["new"][0]
        self.assertEqual(entry["requester"], "unknown")
        self.assertEqual(entry["requested_at"], "")
        self.assertEqual(entry["activity_at"], "")

    def test_should_report_re_request_newer_than_seen(self):
        gh = (FakeGh()
              .on("search prs", search_result(("acme/widgets", 10)))
              .on_lines("issues/10/timeline", [request_event(ME, "2026-09-21T10:00:00Z")])
              .on_lines("pulls/10/comments", []))
        out = self.scan(gh, seen={"acme/widgets#10": "2026-09-20T10:00:00Z"})
        self.assertEqual([e["pr"] for e in out["new"]], [10])
        self.assertEqual(out["new"][0]["trigger"], "requested")
        self.assertEqual(out["already_handled"], 0)

    def test_should_raise_rate_limited_on_search_403(self):
        gh = FakeGh().on("search prs", "", rc=1, stderr="HTTP 403: API rate limit exceeded")
        with self.assertRaises(gh_client.RateLimited):
            self.scan(gh)

    def test_should_make_one_search_and_two_calls_per_pr(self):
        gh = (FakeGh()
              .on("search prs", search_result(("acme/widgets", 10), ("acme/gadgets", 7)))
              .on_lines("timeline", [])
              .on_lines("comments", []))
        self.scan(gh)
        self.assertEqual(gh.count("search prs"), 1)
        self.assertEqual(gh.count("timeline"), 2)
        self.assertEqual(gh.count("comments"), 2)

    # --- search arguments --------------------------------------------------------------------

    def test_should_search_with_one_repo_flag_per_watched_repo(self):
        gh = FakeGh().on("search prs", [])
        self.scan(gh, limit=50)
        self.assertEqual(self.searches(gh), [
            "search prs --repo acme/widgets --repo acme/gadgets --state open --review-requested me-dev "
            "--json repository,number,title,author,url --limit 50"])
        self.assertNotIn("--owner", gh.calls[0][0])

    def test_should_chunk_the_search_by_repos_per_search(self):
        size = review_poll_scan.REPOS_PER_SEARCH
        watched = repo_list(2 * size + 5)
        gh = FakeGh().on("search prs", [])
        out = self.scan(gh, repos=watched)
        searches = self.searches(gh)
        self.assertEqual([len(repo_flags(s)) for s in searches], [size, size, 5])
        self.assertEqual([r for s in searches for r in repo_flags(s)], watched)
        for joined in searches:
            self.assertIn("--review-requested me-dev", joined)
            self.assertIn("--limit 100", joined)
        self.assertEqual(out["pending_total"], 0)
        self.assertFalse(out["truncated"])

    def test_should_put_at_most_twenty_repos_in_one_search(self):
        gh = FakeGh().on("search prs", [])
        self.scan(gh, repos=repo_list(45))
        self.assertEqual([len(repo_flags(s)) for s in self.searches(gh)], [20, 20, 5])

    def test_should_make_one_search_for_exactly_one_chunk(self):
        size = review_poll_scan.REPOS_PER_SEARCH
        gh = FakeGh().on("search prs", [])
        self.scan(gh, repos=repo_list(size))
        self.assertEqual(len(self.searches(gh)), 1)
        gh = FakeGh().on("search prs", [])
        self.scan(gh, repos=repo_list(size + 1))
        self.assertEqual([len(repo_flags(s)) for s in self.searches(gh)], [size, 1])

    def test_should_merge_the_results_of_every_chunk(self):
        size = review_poll_scan.REPOS_PER_SEARCH
        watched = repo_list(size + 1)
        last = watched[-1]
        gh = (FakeGh()
              .on(["search prs", f"--repo {last} "], search_result((last, 2)))
              .on("search prs", search_result(("acme/r00", 1)))
              .on_lines("timeline", [request_event(ME, "2026-09-21T10:00:00Z")])
              .on_lines("comments", []))
        out = self.scan(gh, repos=watched)
        self.assertEqual(out["pending_keys"], ["acme/r00#1", f"{last}#2"])
        self.assertEqual(out["actionable"], 2)

    def test_should_mark_the_scan_truncated_when_any_chunk_hits_the_limit(self):
        size = review_poll_scan.REPOS_PER_SEARCH
        watched = repo_list(size + 1)
        full = search_result(("acme/r00", 1), ("acme/r01", 2))
        gh = (FakeGh()
              .on(["search prs", f"--repo {watched[-1]} "], [])
              .on("search prs", full)
              .on_lines("timeline", [])
              .on_lines("comments", []))
        self.assertTrue(self.scan(gh, repos=watched, limit=2)["truncated"])
        gh = FakeGh().on("search prs", search_result(("acme/r00", 1))).on_lines("timeline", []).on_lines(
            "comments", [])
        self.assertFalse(self.scan(gh, repos=watched, limit=2)["truncated"])

    def test_should_refuse_a_malformed_repo_before_calling_gh(self):
        for bad in ("widgets", "acme/..", "acme/widgets --owner x", ""):
            gh = FakeGh()
            with self.assertRaisesRegex(gh_client.GhError, "invalid repository name", msg=bad):
                self.scan(gh, repos=["acme/widgets", bad])
            self.assertEqual(gh.calls, [])

    def test_should_split_a_list_into_chunks(self):
        self.assertEqual(review_poll_scan.chunks([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(review_poll_scan.chunks([], 2), [])

    def test_should_require_a_repo_on_the_command_line(self):
        argv = ["review_poll_scan.py", "--state", "/nonexistent/ledger.json", "--me", ME]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()), \
                mock.patch.object(review_poll_scan, "GhClient", side_effect=AssertionError("no gh")):
            with self.assertRaises(SystemExit) as raised:
                review_poll_scan.main()
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
