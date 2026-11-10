import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import diffmap  # noqa: E402
from diffmap import FileDiff, FileKind, FileStatus  # noqa: E402
from fakes import DIFF  # noqa: E402


def by_path(records):
    return {record.path: record for record in records}


class ParseDiffTest(unittest.TestCase):
    def setUp(self):
        self.files = by_path(diffmap.parse_diff(DIFF))

    def test_counts_and_new_side_lines(self):
        app = self.files["src/app.py"]
        self.assertEqual((app.added, app.deleted), (3, 1))
        self.assertEqual(app.added_lines, [11, 12, 42])
        self.assertEqual([(h.new_start, h.new_end) for h in app.hunks], [(10, 14), (41, 43)])

    def test_status_of_each_file(self):
        self.assertIs(self.files["src/app.py"].status, FileStatus.MODIFIED)
        self.assertIs(self.files["db/migrations/001.sql"].status, FileStatus.ADDED)
        self.assertIs(self.files["old/gone.py"].status, FileStatus.DELETED)
        renamed = self.files["lib/b.py"]
        self.assertIs(renamed.status, FileStatus.RENAMED)
        self.assertEqual(renamed.old_path, "lib/a.py")

    def test_deleted_file_has_no_anchorable_hunk(self):
        self.assertEqual(self.files["old/gone.py"].hunks, [])
        self.assertNotIn("old/gone.py", diffmap.anchor_map(self.files.values()))

    def test_binary_file_is_noise(self):
        text = "diff --git a/logo.png b/logo.png\nindex 1..2 100644\nBinary files a/logo.png and b/logo.png differ\n"
        (record,) = diffmap.parse_diff(text)
        self.assertTrue(record.binary)
        self.assertIs(record.kind, FileKind.NOISE)

    def test_empty_text_has_no_files(self):
        self.assertEqual(diffmap.parse_diff(""), [])


class ClassifyTest(unittest.TestCase):
    def kind(self, path):
        return diffmap.classify(FileDiff(path=path))

    def test_noise(self):
        for path in ("package-lock.json", "sub/Cargo.lock", "vendor/x/y.php", "web/app.min.js", "node_modules/a/b.js"):
            self.assertIs(self.kind(path), FileKind.NOISE, path)

    def test_data_deploy(self):
        for path in ("db/migrations/001.sql", "Dockerfile", "docker-compose.yml", ".env.example", "package.json",
                     ".github/workflows/ci.yml", "config/services.yaml", "infra/main.tf", "mod/db/install.xml"):
            self.assertIs(self.kind(path), FileKind.DATA_DEPLOY, path)

    def test_code(self):
        for path in ("src/app.py", "docs/config.md", "src/config_loader.py", "README.md"):
            self.assertIs(self.kind(path), FileKind.CODE, path)


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.records = diffmap.parse_diff(DIFF)

    def test_review_diff_drops_noise_and_collapses_deleted_files(self):
        text = diffmap.render(self.records)
        self.assertNotIn("package-lock.json", text)
        self.assertIn("(file deleted: 3 lines", text)
        self.assertNotIn("def gone", text)
        self.assertIn("+    c = 4", text)

    def test_deleted_content_is_kept_separately(self):
        self.assertIn("-def gone():", diffmap.render_deleted(self.records))

    def test_review_lines_count_a_deleted_file_once_and_noise_never(self):
        self.assertEqual(diffmap.review_lines(self.records), 4 + 2 + 1 + 0 + 2)

    def test_data_slice_and_removal_flag(self):
        self.assertEqual([r.path for r in diffmap.data_slice(self.records)], ["db/migrations/001.sql"])
        self.assertTrue(diffmap.removes_or_renames(self.records))
        self.assertFalse(diffmap.removes_or_renames(self.records[:2]))


class ChunkTest(unittest.TestCase):
    def files(self, sizes):
        return [FileDiff(path=f"src/f{i}.py", added=size) for i, size in enumerate(sizes)]

    def test_groups_whole_files_up_to_the_target(self):
        groups = diffmap.chunk(self.files([500, 400, 300, 600]), chunk_lines=800)
        self.assertEqual([[r.added for r in g] for g in groups], [[500], [400, 300], [600]])

    def test_never_more_than_max_chunks(self):
        groups = diffmap.chunk(self.files([900] * 10), chunk_lines=800, max_chunks=4)
        self.assertEqual(len(groups), 4)
        self.assertEqual(sum(len(g) for g in groups), 10)

    def test_noise_is_left_out(self):
        records = self.files([10]) + [FileDiff(path="yarn.lock", added=5000)]
        self.assertEqual([[r.path for r in g] for g in diffmap.chunk(records)], [["src/f0.py"]])


if __name__ == "__main__":
    unittest.main()
