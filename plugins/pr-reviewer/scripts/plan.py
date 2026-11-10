"""Decide which reviewers run for a diff of a given size and shape.

Pure functions over numbers and flags, so the staffing rules can be tested without a diff.

The rules: two independent reviewers always run, because independence is what raises coverage.
Lenses are added only where they pay for themselves: the reach lens when the diff is at least
medium or removes or renames a file, the data-deploy lens when the diff has schema, config or
deploy files and is at least medium, the security lens on large diffs. A very large diff is cut
into chunks for the defect reviewer so no single pass has to hold all of it.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List

MEDIUM_LINES = 200
LARGE_LINES = 600
MONSTER_LINES = 1500


class Band(Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    MONSTER = "monster"

    @property
    def rank(self) -> int:
        return list(Band).index(self)

    def at_least(self, other: "Band") -> bool:
        return self.rank >= other.rank


class Agent(Enum):
    DEFECT = "defect-reviewer"
    CONTEXT = "context-reviewer"
    REACH = "reach-lens"
    DATA_DEPLOY = "data-deploy-lens"
    SECURITY = "security-lens"


@dataclass(frozen=True)
class Shape:
    """What the planner needs to know about a diff."""
    lines: int
    has_tree: bool
    has_data_slice: bool
    removes_or_renames: bool
    chunks: int


@dataclass(frozen=True)
class Stage:
    agent: Agent
    diff: str
    output: str


def band_for(lines: int) -> Band:
    if lines >= MONSTER_LINES:
        return Band.MONSTER
    if lines >= LARGE_LINES:
        return Band.LARGE
    if lines >= MEDIUM_LINES:
        return Band.MEDIUM
    return Band.SMALL


def chunk_file(index: int) -> str:
    return f"chunk-{index + 1}.patch"


def build_stages(shape: Shape) -> List[Stage]:
    band = band_for(shape.lines)
    stages: List[Stage] = []
    if band is Band.MONSTER and shape.chunks > 1:
        stages += [Stage(Agent.DEFECT, chunk_file(i), f"raw/defect-{i + 1}.json") for i in range(shape.chunks)]
    else:
        stages.append(Stage(Agent.DEFECT, "review.patch", "raw/defect.json"))
    stages.append(Stage(Agent.CONTEXT, "review.patch", "raw/context.json"))
    if shape.has_tree and (band.at_least(Band.MEDIUM) or shape.removes_or_renames):
        stages.append(Stage(Agent.REACH, "review.patch", "raw/reach.json"))
    if shape.has_data_slice and band.at_least(Band.MEDIUM):
        stages.append(Stage(Agent.DATA_DEPLOY, "data.patch", "raw/data-deploy.json"))
    if band.at_least(Band.LARGE):
        stages.append(Stage(Agent.SECURITY, "review.patch", "raw/security.json"))
    return stages
