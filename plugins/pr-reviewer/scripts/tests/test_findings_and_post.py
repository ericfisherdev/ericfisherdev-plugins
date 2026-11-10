import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import findings as findings_module  # noqa: E402
import post as post_module  # noqa: E402
from clients import CommandError, Gh  # noqa: E402
from fakes import HEAD, FakeRunner  # noqa: E402
from findings import Anchor, Category, Event, Finding, FindingsError, Severity  # noqa: E402
from ledger import Dirs, Ledger  # noqa: E402
from post import SelectionError  # noqa: E402

REPO = "octo/app"
NOW = "2026-01-01T00:00:00+00:00"


def raw(key, file="src/app.py", line=11, severity="minor", blocking=False, category="correctness", **extra):
    data = {"key": key, "file": file, "line": line, "severity": severity, "blocking": blocking, "category": category,
            "title": f"Title {key}", "body": f"Body {key}.", "sources": ["defect-reviewer"], "checked": "read it"}
    data.update(extra)
    return data


class RunCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dirs = Dirs(self.root, REPO, 7)
        self.dirs.run.mkdir(parents=True)
        self.write("plan.json", {"repo": REPO, "pr": 7, "title": "Add the thing", "head": HEAD, "mode": "full",
                                 "band": "small", "lines": 12, "own_pr": False, "draft": False, "tree": "/tree",
                                 "notes": [], "review_decision": None})
        self.write("anchors.json", {"src/app.py": [[10, 14], [41, 43]]})
        self.gh = FakeRunner()

    def write(self, name, data):
        (self.dirs.run / name).write_text(json.dumps(data), encoding="utf-8")

    def update_plan(self, **fields):
        plan = json.loads((self.dirs.run / "plan.json").read_text(encoding="utf-8"))
        plan.update(fields)
        self.write("plan.json", plan)

    def verified(self, *items, dropped=()):
        self.write("verified.json", {"summary": "Summary.", "findings": list(items), "dropped": list(dropped)})

    def finalize(self):
        return findings_module.finalize(REPO, 7, root=self.root, now=NOW)

    def stored(self):
        return json.loads((self.dirs.run / "findings.json").read_text(encoding="utf-8"))

    def post(self, selection, **kwargs):
        return post_module.post(REPO, 7, selection, gh=Gh(self.gh), root=self.root, **kwargs)

    def payload(self):
        return json.loads((self.dirs.run / "review.json").read_text(encoding="utf-8"))


class FinalizeTest(RunCase):
    def test_orders_numbers_and_anchors(self):
        self.verified(raw("nit", severity="nit", category="style", line=42),
                      raw("off-diff", line=30),
                      raw("major", severity="major", category="error-handling", line=12, start_line=11))
        result = self.finalize()
        self.assertEqual((result["status"], result["total"], result["blocking"]), ("ready", 3, 0))
        stored = self.stored()["findings"]
        self.assertEqual([f["key"] for f in stored], ["major", "off-diff", "nit"])
        self.assertEqual([f["number"] for f in stored], [1, 2, 3])
        self.assertEqual([f["anchor"] for f in stored], ["inline", "body", "inline"])
        self.assertEqual(stored[0]["start_line"], 11)
        self.assertIn("**1. [Major] Title major**", result["markdown"])
        self.assertIn("src/app.py:30 (review body)", result["markdown"])

    def test_start_line_outside_the_hunk_is_dropped(self):
        self.verified(raw("range", line=42, start_line=12))
        self.finalize()
        self.assertIsNone(self.stored()["findings"][0]["start_line"])

    def test_docs_tests_style_and_maintainability_never_block(self):
        self.verified(*[raw(c, severity="major", blocking=True, category=c)
                        for c in ("docs", "test-coverage", "style", "maintainability")])
        result = self.finalize()
        self.assertEqual((result["status"], result["blocking"], result["proposed_event"]), ("ready", 0, "APPROVE"))

    def test_minor_never_blocks_and_critical_always_does(self):
        self.verified(raw("small", severity="minor", blocking=True))
        self.assertEqual(self.finalize()["blocking"], 0)
        self.verified(raw("big", severity="critical", blocking=False))
        self.assertEqual(self.finalize()["status"], "refute")

    def test_blocking_finding_goes_to_the_refuter_first_and_nothing_is_recorded(self):
        self.verified(raw("bad", severity="major", blocking=True))
        result = self.finalize()
        self.assertEqual((result["status"], result["agent"]), ("refute", "pr-reviewer:refuter"))
        self.assertIn(str(self.dirs.run / "refuted.json"), result["prompt"])
        self.assertFalse((self.dirs.run / "findings.json").exists())
        self.assertFalse(self.dirs.ledger.exists())

    def test_refuter_verdicts_are_applied(self):
        self.verified(raw("stands", severity="major", blocking=True, line=11),
                      raw("down", severity="major", blocking=True, line=12),
                      raw("gone", severity="critical", blocking=True, line=42))
        self.write("refuted.json", {"verdicts": [
            {"key": "stands", "file": "src/app.py", "verdict": "stands", "reason": "held"},
            {"key": "down", "file": "src/app.py", "verdict": "downgraded", "severity": "minor", "blocking": False,
             "reason": "guarded upstream"},
            {"key": "gone", "file": "src/app.py", "verdict": "refuted", "reason": "dead branch"}]})
        result = self.finalize()
        self.assertEqual((result["total"], result["blocking"], result["proposed_event"]), (2, 1, "REQUEST_CHANGES"))
        stored = self.stored()
        self.assertEqual([(f["key"], f["severity"], f["blocking"]) for f in stored["findings"]],
                         [("stands", "major", True), ("down", "minor", False)])
        self.assertEqual(stored["dropped"][0]["disposition"], "refuted")
        self.assertEqual(Ledger.load(self.dirs.ledger).findings["src/app.py:gone"]["disposition"], "refuted")

    def test_own_pr_and_draft_propose_a_comment(self):
        self.verified(raw("a"))
        self.update_plan(own_pr=True)
        self.assertEqual(self.finalize()["proposed_event"], "COMMENT")
        self.update_plan(own_pr=False, draft=True)
        self.assertEqual(self.finalize()["proposed_event"], "COMMENT")

    def test_unreviewed_files_cap_a_clean_review_at_comment_but_not_a_change_request(self):
        self.update_plan(unreviewed=["vendor/lib.php"])
        self.verified(raw("a"))
        result = self.finalize()
        self.assertEqual(result["proposed_event"], "COMMENT")
        self.assertIn("so this review cannot approve: `vendor/lib.php`", result["markdown"])
        self.verified(raw("bad", severity="major", blocking=True))
        self.write("refuted.json", {"verdicts": [{"key": "bad", "file": "src/app.py", "verdict": "stands", "reason": "held"}]})
        self.assertEqual(self.finalize()["proposed_event"], "REQUEST_CHANGES")

    def test_pass_is_recorded_as_pending_with_dropped_reasons(self):
        self.verified(raw("a"), dropped=[{"key": "x", "title": "X", "file": "b.py", "line": 1,
                                          "reason": "pre-existing", "disposition": "dropped"}])
        self.finalize()
        ledger = Ledger.load(self.dirs.ledger)
        self.assertEqual(ledger.findings["src/app.py:a"]["disposition"], "pending")
        self.assertEqual(ledger.findings["b.py:x"]["reason"], "pre-existing")
        self.assertFalse(ledger.passes[0]["closed"])
        self.assertIsNone(ledger.last_closed_sha())

    def test_malformed_verifier_output_is_refused(self):
        for bad in ({"findings": "no"}, {"findings": [raw("a", severity="blocker")]},
                    {"findings": [raw("a", category="vibes")]}, {"findings": [raw("a", line="x")]},
                    {"findings": [raw("a"), raw("a")]}, {"findings": [raw("a", body="")]}):
            self.write("verified.json", bad)
            with self.assertRaises(FindingsError, msg=bad):
                self.finalize()

    def test_refuter_verdict_for_an_unknown_finding_is_refused(self):
        self.verified(raw("bad", severity="major", blocking=True))
        self.write("refuted.json", {"verdicts": [{"key": "other", "file": "src/app.py", "verdict": "stands", "reason": "r"}]})
        with self.assertRaises(FindingsError):
            self.finalize()

    def test_no_findings_proposes_approval(self):
        self.verified()
        result = self.finalize()
        self.assertEqual((result["total"], result["proposed_event"]), (0, "APPROVE"))
        self.assertIn("No findings survived verification.", result["markdown"])


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.findings = [Finding("k", "f.py", 1, Severity.MINOR, False, Category.DOCS, "T", "B", number=n) for n in (1, 2, 3)]

    def test_words_and_numbers(self):
        self.assertEqual(post_module.parse_selection("all", self.findings), {1, 2, 3})
        self.assertEqual(post_module.parse_selection("None", self.findings), set())
        self.assertEqual(post_module.parse_selection("1, 3", self.findings), {1, 3})

    def test_bad_values_are_refused(self):
        for bad in ("4", "1,x", "", "0"):
            with self.assertRaises(SelectionError, msg=bad):
                post_module.parse_selection(bad, self.findings)


class EventTest(unittest.TestCase):
    def decide(self, blocking, **flags):
        selected = [Finding("k", "f.py", 1, Severity.MAJOR, blocking, Category.CORRECTNESS, "T", "B")]
        defaults = {"own_pr": False, "draft": False, "head_moved": False, "comment_only": False}
        defaults.update(flags)
        return post_module.decide_event(selected, **defaults)

    def test_follows_the_selection(self):
        self.assertIs(self.decide(True), Event.REQUEST_CHANGES)
        self.assertIs(self.decide(False), Event.APPROVE)

    def test_unreviewed_files_turn_an_approval_into_a_comment_only(self):
        self.assertIs(self.decide(False, unreviewed=True), Event.COMMENT)
        self.assertIs(self.decide(True, unreviewed=True), Event.REQUEST_CHANGES)

    def test_comment_whenever_a_verdict_would_be_wrong(self):
        for flag in ("own_pr", "draft", "head_moved", "comment_only"):
            self.assertIs(self.decide(True, **{flag: True}), Event.COMMENT, flag)


class PostTest(RunCase):
    def setUp(self):
        super().setUp()
        self.verified(raw("inline", line=11, suggestion="    b = 4\n"), raw("body", line=30),
                      raw("range", severity="nit", category="style", line=42, start_line=41))
        self.finalize()
        self.gh.on("-q .headRefOid", HEAD + "\n")

    def test_posts_selected_findings_as_one_approving_review(self):
        self.gh.on("pulls/7/reviews", "https://example.test/review/1\n")
        result = self.post("all")
        self.assertEqual((result["outcome"], result["event"], result["posted"]), ("posted", "APPROVE", 3))
        payload = self.payload()
        self.assertEqual((payload["commit_id"], payload["event"]), (HEAD, "APPROVE"))
        first, second = payload["comments"]
        self.assertEqual((first["path"], first["line"], first["side"]), ("src/app.py", 11, "RIGHT"))
        self.assertIn("```suggestion\n    b = 4\n```", first["body"])
        self.assertEqual((second["start_line"], second["start_side"], second["line"]), (41, "RIGHT", 42))
        self.assertIn("### `src/app.py:30`", payload["body"])
        self.assertIn("**3 comment(s)**, 0 blocking.", payload["body"])
        ledger = Ledger.load(self.dirs.ledger)
        self.assertEqual({f["disposition"] for f in ledger.findings.values()}, {"posted"})
        self.assertEqual(ledger.last_closed_sha(), HEAD)

    def test_unselected_findings_are_recorded_as_declined(self):
        self.gh.on("pulls/7/reviews", "https://example.test/review/1\n")
        self.post("1")
        ledger = Ledger.load(self.dirs.ledger)
        self.assertEqual(sorted(f["disposition"] for f in ledger.findings.values()), ["declined", "declined", "posted"])

    def test_none_posts_nothing_and_closes_the_pass(self):
        result = self.post("none")
        self.assertEqual((result["outcome"], result["posted"]), ("skipped", 0))
        self.assertEqual(self.gh.calls, [])
        self.assertEqual(Ledger.load(self.dirs.ledger).last_closed_sha(), HEAD)

    def test_none_with_approve_posts_a_plain_approval(self):
        self.gh.on("pulls/7/reviews", "https://example.test/review/2\n")
        result = self.post("none", approve=True)
        self.assertEqual((result["outcome"], result["event"]), ("posted", "APPROVE"))
        self.assertNotIn("comments", self.payload())
        self.assertIn("No issues found.", self.payload()["body"])

    def test_moved_head_turns_the_review_into_a_comment(self):
        self.gh.routes.clear()
        self.gh.on("-q .headRefOid", "f" * 40 + "\n")
        self.gh.on("pulls/7/reviews", "https://example.test/review/3\n")
        result = self.post("all")
        self.assertEqual(result["event"], "COMMENT")
        self.assertIn("head moved", self.payload()["body"])

    def test_refused_inline_anchors_fall_back_to_the_review_body(self):
        attempts = []

        def runner(argv, cwd=None):
            joined = " ".join(argv)
            if "headRefOid" in joined:
                return 0, HEAD + "\n", ""
            attempts.append(self.payload())
            return (1, "", "HTTP 422: line must be part of the diff") if len(attempts) == 1 else (0, "https://example.test/r\n", "")

        result = post_module.post(REPO, 7, "all", gh=Gh(runner), root=self.root)
        self.assertEqual(result["outcome"], "posted")
        self.assertIn("comments", attempts[0])
        self.assertNotIn("comments", attempts[1])
        self.assertIn("### `src/app.py:11`", attempts[1]["body"])

    def test_failed_post_records_nothing(self):
        self.gh.on("pulls/7/reviews", rc=1, stderr="HTTP 500")
        with self.assertRaises(CommandError):
            self.post("all")
        ledger = Ledger.load(self.dirs.ledger)
        self.assertIsNone(ledger.last_closed_sha())
        self.assertEqual({f["disposition"] for f in ledger.findings.values()}, {"pending"})

    def test_dry_run_builds_the_payload_and_posts_nothing(self):
        result = self.post("all", dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["payload"]["event"], "APPROVE")
        self.assertEqual(self.gh.count("pulls/7/reviews"), 0)
        self.assertIsNone(Ledger.load(self.dirs.ledger).last_closed_sha())

    def test_unreviewed_files_are_named_and_not_approved(self):
        self.update_plan(unreviewed=["yarn.lock"])
        self.gh.on("pulls/7/reviews", "https://example.test/review/5\n")
        self.assertEqual(self.post("none", approve=True)["event"], "COMMENT")
        self.assertIn("Not reviewed, so not approved: yarn.lock.", self.payload()["body"])

    def test_comment_only_never_approves(self):
        self.gh.on("pulls/7/reviews", "https://example.test/review/4\n")
        self.assertEqual(self.post("all", comment_only=True)["event"], "COMMENT")


class NoFindingsPostTest(RunCase):
    def test_nothing_found_and_nothing_posted_is_a_no_op(self):
        self.verified()
        self.finalize()
        self.assertEqual(self.post("none")["outcome"], "no-op")


class AnchorEnumTest(unittest.TestCase):
    def test_round_trip_keeps_enums(self):
        finding = Finding.from_json(raw("a", anchor="inline", number=2))
        self.assertIs(finding.anchor, Anchor.INLINE)
        self.assertEqual(Finding.from_json(finding.to_json()), finding)


if __name__ == "__main__":
    unittest.main()
