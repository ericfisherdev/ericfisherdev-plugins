import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import intake  # noqa: E402
from clients import CommandError, Gh, Git  # noqa: E402
from fakes import DIFF, HEAD, OLD, FakeRunner, pr_meta  # noqa: E402
from ledger import Dirs, Ledger  # noqa: E402

REPO = "octo/app"
THREADS = {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": [
    {"isResolved": True, "isOutdated": False, "path": "src/app.py", "line": 11,
     "comments": {"nodes": [{"author": {"login": "rev"}, "body": "b should be 3"},
                            {"author": {"login": "author"}, "body": "done"}]}}]}}}}}


class IntakeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "state"
        self.clone = Path(self.tmp.name) / "clone"
        self.clone.mkdir()
        self.dirs = Dirs(self.root, REPO, 7)
        self.gh = FakeRunner()
        self.git = FakeRunner()

    def gh_ready(self, meta=None, diff=DIFF, viewer="me"):
        self.gh.on(["pr view", "--json number"], meta or pr_meta())
        self.gh.on("pr diff", diff)
        self.gh.on("api graphql", THREADS)
        self.gh.on("api user", viewer + "\n")

    def git_clone_elsewhere(self):
        """A clone of the right repository, checked out on some other commit."""
        self.git.on("--show-toplevel", str(self.clone) + "\n")
        self.git.on("remote get-url", "git@github.com:Octo/App.git\n")
        self.git.on("rev-parse HEAD", "c" * 40 + "\n")
        self.git.on(["cat-file", HEAD], rc=1)
        self.git.on("fetch")
        self.git.on("worktree add")
        self.git.on("worktree remove")

    def prepare(self, **kwargs):
        return intake.prepare(REPO, 7, gh=Gh(self.gh), git=Git(self.git), root=self.root, cwd=str(self.clone), **kwargs)

    def close_pass_at(self, sha):
        ledger = Ledger.load(self.dirs.ledger)
        ledger.open_pass({"sha": sha})
        ledger.close_pass(sha)
        ledger.save()


class StopTest(IntakeCase):
    def test_closed_pr_is_a_no_op(self):
        self.gh.on(["pr view", "--json number"], pr_meta(state="MERGED"))
        result = self.prepare()
        self.assertEqual((result["status"], result["outcome"]), ("stop", "no-op"))
        self.assertEqual(self.gh.count("pr diff"), 0)

    def test_head_already_reviewed_is_a_no_op_unless_forced(self):
        self.close_pass_at(HEAD)
        self.gh_ready()
        self.git_clone_elsewhere()
        self.assertEqual(self.prepare()["status"], "stop")
        self.assertEqual(self.prepare(force_full=True)["status"], "ready")

    def test_empty_diff_is_a_no_op(self):
        self.gh_ready(diff="")
        self.assertEqual(self.prepare()["outcome"], "no-op")

    def test_unreadable_pr_raises(self):
        self.gh.on("pr view", rc=1, stderr="Could not resolve to a Repository")
        with self.assertRaises(CommandError):
            self.prepare()


class TreeTest(IntakeCase):
    def test_creates_a_detached_worktree_and_never_checks_out_in_the_clone(self):
        self.gh_ready()
        self.git_clone_elsewhere()
        result = self.prepare()
        self.assertEqual(result["tree"], str(self.dirs.tree))
        self.assertEqual(result["tree_host"], str(self.clone))
        self.assertEqual(self.git.count("fetch --quiet origin pull/7/head"), 1)
        self.assertEqual(self.git.count(f"worktree add --detach --quiet {self.dirs.tree} {HEAD}"), 1)
        self.assertEqual(self.git.count("checkout"), 0)

    def test_uses_the_working_directory_when_it_is_clean_at_the_head(self):
        self.gh_ready()
        self.git.on("--show-toplevel", str(self.clone) + "\n")
        self.git.on("remote get-url", "https://github.com/octo/app\n")
        self.git.on("rev-parse HEAD", HEAD + "\n")
        self.git.on("status --porcelain", "")
        result = self.prepare()
        self.assertEqual(result["tree"], str(self.clone))
        self.assertIsNone(result["tree_host"])
        self.assertEqual(self.git.count("worktree"), 0)

    def test_a_clone_of_another_repository_gives_a_diff_only_review(self):
        self.gh_ready()
        self.git.on("--show-toplevel", str(self.clone) + "\n")
        self.git.on("remote get-url", "git@github.com:octo/other.git\n")
        result = self.prepare()
        self.assertIsNone(result["tree"])
        self.assertNotIn("pr-reviewer:reach-lens", [s["agent"] for s in result["stages"]])
        self.assertIn("diff alone", result["notes"][0])

    def test_a_failed_worktree_falls_back_to_the_diff(self):
        self.gh_ready()
        self.git.on("--show-toplevel", str(self.clone) + "\n")
        self.git.on("remote get-url", "git@github.com:octo/app.git\n")
        self.git.on("rev-parse HEAD", "c" * 40 + "\n")
        self.git.on("cat-file", rc=1)
        self.git.on("fetch", rc=1, stderr="no such ref")
        result = self.prepare()
        self.assertIsNone(result["tree"])
        self.assertEqual(result["status"], "ready")


class PackTest(IntakeCase):
    def setUp(self):
        super().setUp()
        self.gh_ready()
        self.git_clone_elsewhere()
        self.result = self.prepare()

    def read(self, name):
        return (self.dirs.run / name).read_text(encoding="utf-8")

    def test_plan_names_the_agents_and_absolute_paths(self):
        agents = [s["agent"] for s in self.result["stages"]]
        self.assertEqual(agents, ["pr-reviewer:defect-reviewer", "pr-reviewer:context-reviewer", "pr-reviewer:reach-lens"])
        for stage in self.result["stages"]:
            self.assertIn(str(self.dirs.run / "manifest.md"), stage["prompt"])
            self.assertIn(str(self.dirs.tree), stage["prompt"])
        self.assertIn(str(self.dirs.run / "verified.json"), self.result["verifier"]["prompt"])
        self.assertEqual(json.loads(self.read("plan.json"))["head"], HEAD)

    def test_pack_files(self):
        self.assertIn("octo/app#7: Add the thing", self.read("manifest.md"))
        self.assertIn("`package-lock.json`", self.read("manifest.md"))
        self.assertNotIn("package-lock.json", self.read("review.patch"))
        self.assertIn("CREATE TABLE", self.read("data.patch"))
        self.assertIn("def gone", self.read("deleted.patch"))
        self.assertEqual(json.loads(self.read("anchors.json"))["src/app.py"], [[10, 14], [41, 43]])
        self.assertTrue((self.dirs.run / "raw").is_dir())

    def test_prior_feedback_lists_threads_and_replies(self):
        prior = self.read("prior.md")
        self.assertIn("- [resolved] src/app.py:11 @rev: b should be 3", prior)
        self.assertIn("last of 1 replies, @author: done", prior)

    def test_own_pr_is_detected(self):
        self.assertFalse(self.result["own_pr"])
        self.gh.routes.clear()
        self.gh_ready(viewer="author")
        self.assertTrue(self.prepare()["own_pr"])


class DegradedLookupTest(IntakeCase):
    def test_denied_api_calls_do_not_stop_the_review(self):
        self.gh.on(["pr view", "--json number"], pr_meta())
        self.gh.on("pr diff", DIFF)
        self.gh.on("api graphql", rc=1, stderr="denied")
        self.gh.on("api user", rc=1, stderr="denied")
        self.git_clone_elsewhere()
        result = self.prepare()
        self.assertEqual(result["status"], "ready")
        self.assertFalse(result["own_pr"])
        self.assertIn("unavailable", (self.dirs.run / "prior.md").read_text(encoding="utf-8"))


class IncrementalTest(IntakeCase):
    DELTA = "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n@@ -41,2 +41,3 @@\n x = 1\n+    y = 2\n return x\n"

    def setUp(self):
        super().setUp()
        self.close_pass_at(OLD)
        self.gh_ready()
        self.git.on("--show-toplevel", str(self.clone) + "\n")
        self.git.on("remote get-url", "git@github.com:octo/app.git\n")
        self.git.on("rev-parse HEAD", "c" * 40 + "\n")
        self.git.on(["cat-file", HEAD], rc=0)
        self.git.on("worktree add")

    def test_reviews_only_the_range_but_anchors_against_the_whole_pr(self):
        self.git.on(["cat-file", OLD], rc=0)
        self.git.on(f"diff {OLD}..{HEAD}", self.DELTA)
        result = self.prepare()
        self.assertEqual(result["mode"], "incremental")
        self.assertEqual(result["lines"], 1)
        self.assertNotIn("CREATE TABLE", (self.dirs.run / "review.patch").read_text(encoding="utf-8"))
        self.assertIn("db/migrations/001.sql", json.loads((self.dirs.run / "anchors.json").read_text(encoding="utf-8")))

    def test_no_content_change_since_the_last_pass_is_a_no_op(self):
        self.git.on(["cat-file", OLD], rc=0)
        self.git.on(f"diff {OLD}..{HEAD}", "")
        self.assertEqual(self.prepare()["outcome"], "no-op")

    def test_rewritten_history_falls_back_to_a_full_review(self):
        self.git.on(["cat-file", OLD], rc=1)
        result = self.prepare()
        self.assertEqual(result["mode"], "full")
        self.assertTrue(any("not reachable" in note for note in result["notes"]))


class CleanupTest(IntakeCase):
    def test_removes_only_a_worktree_it_created(self):
        self.gh_ready()
        self.git_clone_elsewhere()
        self.prepare()
        self.dirs.tree.mkdir(parents=True)
        result = intake.cleanup(REPO, 7, git=Git(self.git), root=self.root)
        self.assertTrue(result["removed"])
        self.assertEqual(self.git.count(f"worktree remove --force {self.dirs.tree}"), 1)

    def test_nothing_to_remove_without_a_plan(self):
        self.assertFalse(intake.cleanup(REPO, 7, git=Git(self.git), root=self.root)["removed"])


if __name__ == "__main__":
    unittest.main()
