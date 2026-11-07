import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import repos  # noqa: E402
from gh_client import GhError, RateLimited  # noqa: E402


class Canonical:
    """An injected `canonical` callable: maps a name to GitHub's spelling, or raises for unknown repos."""

    def __init__(self, spellings=None, missing=()):
        self.spellings = spellings or {}
        self.missing = set(missing)
        self.calls = []

    def __call__(self, name):
        self.calls.append(name)
        if name in self.missing:
            raise GhError("GraphQL: Could not resolve to a Repository")
        return self.spellings.get(name, name)


class FullNameTest(unittest.TestCase):
    def test_should_accept_well_formed_owner_and_name(self):
        for name in ("acme/widgets", "a/b", "acme-co/widgets.js", "Acme/Widgets_2", "acme/.github",
                     "a" * 39 + "/x", "acme/" + "w" * 100):
            self.assertTrue(repos.is_full_name(name), name)

    def test_should_refuse_anything_that_is_not_owner_and_name(self):
        for name in ("widgets", "acme/", "/widgets", "-acme/widgets", "acme/wid gets", "acme/..", "acme/.",
                     "a/b/c", "a" * 40 + "/x", "acme/" + "w" * 101, "acme/widgets;rm", "acme_co/widgets",
                     "", None, 5, ["acme/widgets"]):
            self.assertFalse(repos.is_full_name(name), repr(name))

    def test_should_strip_a_parsed_name_and_raise_for_a_malformed_one(self):
        self.assertEqual(repos.parse_full_name("  acme/widgets \n"), "acme/widgets")
        for value in ("widgets", "acme/..", " ", None):
            with self.assertRaisesRegex(repos.RepoError, "owner/name", msg=repr(value)):
                repos.parse_full_name(value)


class ReposFileCase(unittest.TestCase):
    """Shared temp repos.json; holds no tests of its own."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "review-watcher" / "repos.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding="utf-8")

    def stored(self):
        return json.loads(self.path.read_text(encoding="utf-8"))


class ReposFileTest(ReposFileCase):

    def test_should_live_in_the_state_dir(self):
        self.assertEqual(repos.repos_path({"CLAUDE_CONFIG_DIR": "/cfg"}), Path("/cfg") / "review-watcher" / "repos.json")
        self.assertEqual(repos.repos_path({}, home="/home/x"),
                         Path("/home/x") / ".claude" / "review-watcher" / "repos.json")

    def test_should_read_a_missing_file_or_a_missing_key_as_no_repos(self):
        self.assertEqual(repos.read_repos(self.path), [])
        self.write("{}")
        self.assertEqual(repos.read_repos(self.path), [])

    def test_should_read_the_stored_repos(self):
        self.write('{"repos": ["acme/widgets", "acme/gadgets"]}')
        self.assertEqual(repos.read_repos(self.path), ["acme/widgets", "acme/gadgets"])

    def test_should_raise_a_repo_error_for_a_corrupt_file(self):
        cases = {
            "{broken": "not valid JSON",
            "": "not valid JSON",
            '["acme/widgets"]': "must hold a JSON object",
            '{"repos": "acme/widgets"}': "must hold",
            '{"repos": {"acme/widgets": true}}': "must hold",
            '{"repos": ["acme/widgets", "not a repo"]}': "must hold",
            '{"repos": ["acme/widgets", 5]}': "must hold",
            '{"repos": ["acme/.."]}': "must hold",
        }
        for text, message in cases.items():
            self.write(text)
            with self.assertRaisesRegex(repos.RepoError, message, msg=text):
                repos.read_repos(self.path)

    def test_should_name_the_file_in_a_corrupt_file_error(self):
        self.write('{"repos": [1]}')
        with self.assertRaisesRegex(repos.RepoError, "fix or delete it") as raised:
            repos.read_repos(self.path)
        self.assertIn(str(self.path), str(raised.exception))

    def test_should_raise_a_repo_error_for_an_unreadable_file(self):
        self.path.mkdir(parents=True)
        with self.assertRaisesRegex(repos.RepoError, "cannot read"):
            repos.read_repos(self.path)

    def test_should_write_the_repos_sorted_without_regard_to_case(self):
        repos.write_repos(self.path, ["acme/zeta", "Acme/Beta", "acme/alpha"])
        self.assertEqual(self.stored(), {"repos": ["acme/alpha", "Acme/Beta", "acme/zeta"]})
        self.assertEqual(os.listdir(self.path.parent), ["repos.json"])


class AddTest(ReposFileCase):
    def test_should_add_each_repo_in_its_canonical_spelling(self):
        canonical = Canonical({"acme/widgets": "Acme/Widgets"})
        out = repos.add(self.path, [" acme/widgets ", "acme/gadgets"], canonical)
        self.assertEqual(canonical.calls, ["acme/widgets", "acme/gadgets"])
        self.assertEqual(out, {"repos": ["acme/gadgets", "Acme/Widgets"], "added": ["Acme/Widgets", "acme/gadgets"],
                               "already": []})
        self.assertEqual(self.stored(), {"repos": ["acme/gadgets", "Acme/Widgets"]})

    def test_should_report_a_repo_already_watched_under_another_case(self):
        repos.write_repos(self.path, ["Acme/Widgets"])
        out = repos.add(self.path, ["acme/widgets", "acme/gadgets"], Canonical())
        self.assertEqual(out["added"], ["acme/gadgets"])
        self.assertEqual(out["already"], ["acme/widgets"])
        self.assertEqual(self.stored(), {"repos": ["acme/gadgets", "Acme/Widgets"]})

    def test_should_dedupe_within_one_call(self):
        out = repos.add(self.path, ["acme/widgets", "ACME/WIDGETS"], Canonical())
        self.assertEqual((out["added"], out["already"]), (["acme/widgets"], ["ACME/WIDGETS"]))
        self.assertEqual(self.stored(), {"repos": ["acme/widgets"]})

    def test_should_dedupe_by_the_canonical_spelling(self):
        repos.write_repos(self.path, ["Acme/Widgets"])
        canonical = Canonical({"acme/old-widgets": "Acme/Widgets"})
        out = repos.add(self.path, ["acme/old-widgets"], canonical)
        self.assertEqual((out["added"], out["already"]), ([], ["Acme/Widgets"]))

    def test_should_refuse_and_write_nothing_when_gh_answers_a_malformed_name(self):
        repos.write_repos(self.path, ["acme/widgets"])
        before = self.path.read_bytes()
        for answer in ("", "not a repo", "acme/.."):
            with self.assertRaisesRegex(repos.RepoError, "expected an owner/name"):
                repos.add(self.path, ["acme/gadgets"], Canonical({"acme/gadgets": answer}))
        self.assertEqual(self.path.read_bytes(), before)

    def test_should_write_nothing_when_every_repo_is_already_watched(self):
        self.write('{"repos": ["acme/widgets"]}')
        before = self.path.read_bytes()
        out = repos.add(self.path, ["acme/widgets"], Canonical())
        self.assertEqual(out, {"repos": ["acme/widgets"], "added": [], "already": ["acme/widgets"]})
        self.assertEqual(self.path.read_bytes(), before)

    def test_should_write_nothing_when_any_name_is_malformed(self):
        repos.write_repos(self.path, ["acme/widgets"])
        before = self.path.read_bytes()
        with self.assertRaisesRegex(repos.RepoError, "owner/name"):
            repos.add(self.path, ["acme/gadgets", "gizmos"], Canonical())
        self.assertEqual(self.path.read_bytes(), before)

    def test_should_write_nothing_when_gh_cannot_see_a_repo(self):
        canonical = Canonical(missing={"acme/secret"})
        with self.assertRaisesRegex(repos.RepoError, "gh cannot see acme/secret"):
            repos.add(self.path, ["acme/gadgets", "acme/secret"], canonical)
        self.assertFalse(self.path.exists())

    def test_should_refuse_when_gh_is_rate_limited(self):
        def limited(name):
            raise RateLimited("HTTP 429")

        with self.assertRaisesRegex(repos.RepoError, "gh cannot see"):
            repos.add(self.path, ["acme/widgets"], limited)
        self.assertFalse(self.path.exists())

    def test_should_not_ask_gh_or_write_when_the_file_is_corrupt(self):
        self.write("{broken")
        canonical = Canonical()
        with self.assertRaises(repos.RepoError):
            repos.add(self.path, ["acme/widgets"], canonical)
        self.assertEqual(canonical.calls, [])
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{broken")


class RemoveTest(ReposFileCase):
    def test_should_remove_a_repo_without_regard_to_case(self):
        repos.write_repos(self.path, ["Acme/Widgets", "acme/gadgets"])
        out = repos.remove(self.path, ["acme/widgets"])
        self.assertEqual(out, {"repos": ["acme/gadgets"], "removed": ["Acme/Widgets"], "missing": []})
        self.assertEqual(self.stored(), {"repos": ["acme/gadgets"]})

    def test_should_report_names_that_are_not_watched(self):
        repos.write_repos(self.path, ["acme/widgets", "acme/gadgets"])
        out = repos.remove(self.path, ["acme/gadgets", " acme/gizmos "])
        self.assertEqual(out, {"repos": ["acme/widgets"], "removed": ["acme/gadgets"], "missing": ["acme/gizmos"]})

    def test_should_write_nothing_when_nothing_was_removed(self):
        out = repos.remove(self.path, ["acme/widgets"])
        self.assertEqual(out, {"repos": [], "removed": [], "missing": ["acme/widgets"]})
        self.assertFalse(self.path.exists())
        self.write('{"repos": ["acme/gadgets"]}')
        before = self.path.read_bytes()
        repos.remove(self.path, ["acme/widgets"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_should_keep_an_empty_list_after_removing_the_last_repo(self):
        repos.write_repos(self.path, ["acme/widgets"])
        repos.remove(self.path, ["acme/widgets"])
        self.assertEqual(self.stored(), {"repos": []})
        self.assertEqual(repos.read_repos(self.path), [])

    def test_should_refuse_a_malformed_name_and_write_nothing(self):
        repos.write_repos(self.path, ["acme/widgets"])
        before = self.path.read_bytes()
        with self.assertRaisesRegex(repos.RepoError, "owner/name"):
            repos.remove(self.path, ["acme/widgets", "widgets"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_should_refuse_a_corrupt_file_and_leave_it_alone(self):
        self.write('{"repos": "acme/widgets"}')
        with self.assertRaises(repos.RepoError):
            repos.remove(self.path, ["acme/widgets"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), '{"repos": "acme/widgets"}')


class FakeClient:
    def __init__(self, canonical):
        self.canonical_repo = canonical


class MainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "review-watcher" / "repos.json"
        patcher = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.canonical = Canonical({"acme/widgets": "Acme/Widgets"}, missing={"acme/secret"})

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = repos.main(list(argv), gh_factory=lambda: FakeClient(self.canonical))
        return code, json.loads(out.getvalue())

    def test_should_list_add_and_remove_through_the_cli(self):
        self.assertEqual(self.run_cli("list"), (0, {"repos": [], "file": str(self.path)}))
        code, out = self.run_cli("add", "acme/widgets", "acme/gadgets")
        self.assertEqual(code, 0)
        self.assertEqual(out["added"], ["Acme/Widgets", "acme/gadgets"])
        self.assertEqual(out["file"], str(self.path))
        self.assertEqual(self.run_cli("list")[1]["repos"], ["acme/gadgets", "Acme/Widgets"])
        code, out = self.run_cli("remove", "acme/gadgets", "acme/gizmos")
        self.assertEqual((code, out["removed"], out["missing"]), (0, ["acme/gadgets"], ["acme/gizmos"]))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"repos": ["Acme/Widgets"]})

    def test_should_print_an_error_and_exit_1_when_a_name_is_refused(self):
        for argv in (("add", "widgets"), ("add", "acme/widgets", "acme/secret"), ("remove", "a/b/c")):
            code, out = self.run_cli(*argv)
            self.assertEqual(code, 1, argv)
            self.assertEqual(set(out), {"error"}, argv)
        self.assertFalse(self.path.exists())

    def test_should_print_an_error_and_exit_1_for_a_corrupt_file(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{broken", encoding="utf-8")
        for argv in (("list",), ("add", "acme/gadgets"), ("remove", "acme/gadgets")):
            code, out = self.run_cli(*argv)
            self.assertEqual(code, 1, argv)
            self.assertIn("not valid JSON", out["error"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{broken")

    def test_should_require_at_least_one_name(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for action in ("add", "remove"):
                with self.assertRaises(SystemExit, msg=action):
                    repos.main([action], gh_factory=lambda: FakeClient(self.canonical))


if __name__ == "__main__":
    unittest.main()
