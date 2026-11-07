import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import gh_client  # noqa: E402
from fake_gh import FakeGh  # noqa: E402


class CaptureExit:
    """Swallow SystemExit and keep its code."""

    def __enter__(self):
        self.code = 0
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is SystemExit:
            self.code = exc.code
            return True
        return False


def run_guarded(fn):
    """Run fn under main_guard; return (parsed stdout JSON, exit code)."""
    buf = io.StringIO()
    with redirect_stdout(buf), CaptureExit() as exit_:
        gh_client.main_guard(fn)
    return json.loads(buf.getvalue()), exit_.code


def stalled_run(*args, **kwargs):
    raise gh_client.subprocess.TimeoutExpired(cmd="gh", timeout=kwargs.get("timeout"))


class GhClientErrorTest(unittest.TestCase):
    def test_should_raise_rate_limited_on_429_and_secondary_limit(self):
        for stderr in ("HTTP 429: Too Many Requests", "You have exceeded a secondary rate limit"):
            client = gh_client.GhClient(runner=FakeGh().on("api", "", rc=1, stderr=stderr))
            with self.assertRaises(gh_client.RateLimited):
                client.run(["api", "user"])

    def test_should_turn_a_gh_timeout_into_gh_error(self):
        client = gh_client.GhClient(
            runner=lambda args, input=None: gh_client.subprocess_runner(args, input, run=stalled_run))
        with self.assertRaises(gh_client.GhError) as ctx:
            client.run(["api", "user"])
        self.assertIn("timed out", str(ctx.exception))

    def test_should_turn_a_missing_gh_executable_into_gh_error(self):
        def missing(*args, **kwargs):
            raise FileNotFoundError("gh")
        with self.assertRaises(gh_client.GhError) as ctx:
            gh_client.subprocess_runner(["api", "user"], run=missing)
        self.assertIn("GitHub CLI", str(ctx.exception))
        self.assertIn("PATH", str(ctx.exception))

    def test_should_raise_plain_gh_error_on_404(self):
        client = gh_client.GhClient(runner=FakeGh().on("api", "", rc=1, stderr="gh: Not Found (HTTP 404)"))
        with self.assertRaises(gh_client.GhError) as ctx:
            client.run(["api", "repos/x"])
        self.assertNotIsInstance(ctx.exception, gh_client.RateLimited)

    def test_should_print_rate_limited_json_and_exit_2(self):
        def fn():
            raise gh_client.RateLimited("HTTP 403: API rate limit exceeded")
        self.assertEqual(run_guarded(fn), ({"error": "rate_limited"}, 2))

    def test_should_print_gh_failed_json_and_exit_1(self):
        def fn():
            raise gh_client.GhError("boom")
        self.assertEqual(run_guarded(fn), ({"error": "gh_failed", "detail": "boom"}, 1))

    def test_should_print_internal_json_instead_of_traceback(self):
        def fn():
            raise KeyError("data")
        out, code = run_guarded(fn)
        self.assertEqual(out["error"], "internal")
        self.assertIn("KeyError", out["detail"])
        self.assertEqual(code, 1)


class GhClientQueryTest(unittest.TestCase):
    def test_should_ask_gh_for_the_canonical_owner_and_name(self):
        fake = FakeGh().on("repo view", "Acme/Widgets\n")
        client = gh_client.GhClient(runner=fake)
        self.assertEqual(client.canonical_repo("acme/widgets"), "Acme/Widgets")
        self.assertEqual(fake.calls[0][0], "repo view acme/widgets --json nameWithOwner --jq .nameWithOwner")

    def test_should_raise_gh_error_for_a_repository_gh_cannot_see(self):
        fake = FakeGh().on("repo view", rc=1, stderr="GraphQL: Could not resolve to a Repository")
        with self.assertRaises(gh_client.GhError):
            gh_client.GhClient(runner=fake).canonical_repo("acme/missing")

    def test_should_flatten_every_page_of_a_rest_list(self):
        fake = FakeGh().on_lines("issues/1/timeline", [{"id": 1}, {"id": 2}])
        client = gh_client.GhClient(runner=fake)
        self.assertEqual(client.rest_list("repos/acme/widgets/issues/1/timeline"), [{"id": 1}, {"id": 2}])
        self.assertEqual(fake.calls[0][0], "api repos/acme/widgets/issues/1/timeline --paginate --jq .[]")

    def test_should_read_the_current_login(self):
        client = gh_client.GhClient(runner=FakeGh().on("api user", "me-dev\n"))
        self.assertEqual(client.current_login(), "me-dev")


class LoadStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "state.json")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_should_treat_a_missing_state_file_as_empty_state(self):
        self.assertEqual(gh_client.load_state(self.path), {})

    def test_should_read_a_valid_state_file(self):
        self.write('{"seen": {"acme/widgets#1": "2026-01-01T00:00:00Z"}}')
        self.assertEqual(gh_client.load_state(self.path), {"seen": {"acme/widgets#1": "2026-01-01T00:00:00Z"}})

    def test_should_name_the_path_when_the_state_file_is_half_written(self):
        for text in ("", '{"seen": {"acme/widgets#1"'):
            self.write(text)
            with self.assertRaises(gh_client.StateError) as ctx:
                gh_client.load_state(self.path)
            self.assertIn(self.path, str(ctx.exception))
            self.assertIn("fix or delete it", str(ctx.exception))

    def test_should_reject_a_state_file_that_is_not_a_json_object(self):
        self.write("[]")
        with self.assertRaises(gh_client.StateError):
            gh_client.load_state(self.path)

    def test_should_print_bad_state_json_and_exit_1(self):
        self.write("{")

        def fn():
            gh_client.load_state(self.path)
        out, code = run_guarded(fn)
        self.assertEqual(out["error"], "bad_state")
        self.assertIn(self.path, out["detail"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
