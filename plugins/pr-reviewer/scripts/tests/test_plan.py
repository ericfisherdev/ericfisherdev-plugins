import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plan import Agent, Band, Shape, band_for, build_stages  # noqa: E402


def agents(**shape):
    defaults = {"lines": 50, "has_tree": True, "has_data_slice": False, "removes_or_renames": False, "chunks": 0}
    defaults.update(shape)
    return [stage.agent for stage in build_stages(Shape(**defaults))]


class BandTest(unittest.TestCase):
    def test_boundaries(self):
        self.assertIs(band_for(0), Band.SMALL)
        self.assertIs(band_for(199), Band.SMALL)
        self.assertIs(band_for(200), Band.MEDIUM)
        self.assertIs(band_for(599), Band.MEDIUM)
        self.assertIs(band_for(600), Band.LARGE)
        self.assertIs(band_for(1499), Band.LARGE)
        self.assertIs(band_for(1500), Band.MONSTER)


class StagesTest(unittest.TestCase):
    def test_small_diff_gets_the_two_independent_reviewers_only(self):
        self.assertEqual(agents(lines=50, has_data_slice=True), [Agent.DEFECT, Agent.CONTEXT])

    def test_small_diff_that_removes_a_file_adds_the_reach_lens(self):
        self.assertEqual(agents(lines=20, removes_or_renames=True), [Agent.DEFECT, Agent.CONTEXT, Agent.REACH])

    def test_medium_diff_adds_reach_and_data_deploy_when_it_has_a_slice(self):
        self.assertEqual(agents(lines=300), [Agent.DEFECT, Agent.CONTEXT, Agent.REACH])
        self.assertEqual(agents(lines=300, has_data_slice=True),
                         [Agent.DEFECT, Agent.CONTEXT, Agent.REACH, Agent.DATA_DEPLOY])

    def test_no_tree_means_no_reach_lens(self):
        self.assertNotIn(Agent.REACH, agents(lines=900, has_tree=False, removes_or_renames=True))

    def test_large_diff_adds_the_security_lens(self):
        self.assertEqual(agents(lines=700), [Agent.DEFECT, Agent.CONTEXT, Agent.REACH, Agent.SECURITY])

    def test_monster_diff_runs_the_defect_reviewer_per_chunk(self):
        stages = build_stages(Shape(lines=2400, has_tree=True, has_data_slice=False, removes_or_renames=False, chunks=3))
        defect = [s for s in stages if s.agent is Agent.DEFECT]
        self.assertEqual([s.diff for s in defect], ["chunk-1.patch", "chunk-2.patch", "chunk-3.patch"])
        self.assertEqual(len({s.output for s in stages}), len(stages))
        self.assertEqual([s.diff for s in stages if s.agent is Agent.CONTEXT], ["review.patch"])

    def test_monster_diff_in_one_chunk_uses_the_whole_diff(self):
        stages = build_stages(Shape(lines=1600, has_tree=True, has_data_slice=False, removes_or_renames=False, chunks=1))
        self.assertEqual([s.diff for s in stages if s.agent is Agent.DEFECT], ["review.patch"])


if __name__ == "__main__":
    unittest.main()
