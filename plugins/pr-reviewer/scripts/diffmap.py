"""Parse a unified diff into per-file records and cut it into the slices the reviewers read.

Standard library only. Nothing here touches git or GitHub: every function takes diff text or
parsed records and returns data, so the planner and the anchoring check share one parser.
"""

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Tuple

FILE_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

# Changed lines one chunk of a very large diff may hold, and how many chunks a review may fan out to.
CHUNK_LINES = 800
MAX_CHUNKS = 4

LOCKFILES = frozenset({
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "composer.lock",
    "cargo.lock", "poetry.lock", "uv.lock", "pipfile.lock", "gemfile.lock", "go.sum", "flake.lock",
})
GENERATED_DIRS = frozenset({"node_modules", "vendor", "dist", "__snapshots__"})
GENERATED_SUFFIXES = (".min.js", ".min.css", ".map", ".snap")

MANIFESTS = frozenset({
    "package.json", "composer.json", "pyproject.toml", "cargo.toml", "go.mod", "gemfile", "pom.xml",
    "build.gradle", "build.gradle.kts", "setup.py", "setup.cfg",
})
DEPLOY_DIRS = frozenset({
    "migrations", "migration", "migrate", "db", "database", "schema", "infra", "infrastructure", "deploy",
    "deployment", "helm", "k8s", "kubernetes", "terraform", "ansible", "cron", "config", "conf",
})
DEPLOY_SUFFIXES = (".sql", ".tf", ".tfvars")
DEPLOY_NAME = re.compile(r"^(dockerfile.*|docker-compose.*|compose\.ya?ml|\.env.*|.*\.env|crontab.*|procfile|"
                         r"requirements.*\.txt|install\.xml|upgrade\.php)$")
CONFIG_SUFFIXES = (".yml", ".yaml", ".json", ".toml", ".ini", ".xml", ".conf", ".properties", ".php", ".py", ".rb")


class FileStatus(Enum):
    ADDED = "added"
    DELETED = "deleted"
    MODIFIED = "modified"
    RENAMED = "renamed"


class FileKind(Enum):
    CODE = "code"
    DATA_DEPLOY = "data-deploy"
    NOISE = "noise"


@dataclass
class Hunk:
    new_start: int
    new_count: int

    @property
    def new_end(self) -> int:
        return self.new_start + self.new_count - 1


@dataclass
class FileDiff:
    path: str
    old_path: Optional[str] = None
    status: FileStatus = FileStatus.MODIFIED
    binary: bool = False
    added: int = 0
    deleted: int = 0
    hunks: List[Hunk] = field(default_factory=list)
    added_lines: List[int] = field(default_factory=list)
    text: str = ""

    @property
    def changed(self) -> int:
        return self.added + self.deleted

    @property
    def kind(self) -> FileKind:
        return classify(self)

    @property
    def review_lines(self) -> int:
        """Changed lines a reviewer has to read. A deleted file is shown as one marker line."""
        if self.kind is FileKind.NOISE:
            return 0
        return 1 if self.status is FileStatus.DELETED else self.changed


def parse_diff(text: str) -> List[FileDiff]:
    files: List[FileDiff] = []
    current: Optional[FileDiff] = None
    section: List[str] = []
    new_line = 0
    in_hunk = False

    def close():
        if current is not None:
            current.text = "\n".join(section) + "\n"
            files.append(current)

    for line in text.splitlines():
        header = FILE_HEADER.match(line)
        if header:
            close()
            current = FileDiff(path=header.group(2), old_path=header.group(1))
            section = [line]
            in_hunk = False
            continue
        if current is None:
            continue
        section.append(line)
        hunk = HUNK_HEADER.match(line)
        if hunk:
            new_line = int(hunk.group(1))
            count = int(hunk.group(2)) if hunk.group(2) is not None else 1
            if count > 0:
                current.hunks.append(Hunk(new_line, count))
            in_hunk = True
        elif in_hunk:
            new_line = _consume_body_line(current, line, new_line)
        else:
            _consume_meta_line(current, line)
    close()
    for record in files:
        if record.status is not FileStatus.RENAMED and record.old_path == record.path:
            record.old_path = None
    return files


def _consume_meta_line(record: FileDiff, line: str) -> None:
    if line.startswith("new file mode"):
        record.status = FileStatus.ADDED
    elif line.startswith("deleted file mode"):
        record.status = FileStatus.DELETED
    elif line.startswith("rename from "):
        record.status = FileStatus.RENAMED
        record.old_path = line[len("rename from "):]
    elif line.startswith("rename to "):
        record.path = line[len("rename to "):]
    elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
        record.binary = True


def _consume_body_line(record: FileDiff, line: str, new_line: int) -> int:
    if line.startswith("+"):
        record.added += 1
        record.added_lines.append(new_line)
        return new_line + 1
    if line.startswith("-"):
        record.deleted += 1
        return new_line
    if line.startswith("\\"):
        return new_line
    return new_line + 1


def classify(record: FileDiff) -> FileKind:
    path = PurePosixPath(record.path.lower())
    name = path.name
    dirs = set(path.parts[:-1])
    if record.binary or name in LOCKFILES or dirs & GENERATED_DIRS or name.endswith(GENERATED_SUFFIXES):
        return FileKind.NOISE
    if name in MANIFESTS or name.endswith(DEPLOY_SUFFIXES) or DEPLOY_NAME.match(name):
        return FileKind.DATA_DEPLOY
    if ".github" in dirs and "workflows" in dirs:
        return FileKind.DATA_DEPLOY
    if dirs & DEPLOY_DIRS and name.endswith(CONFIG_SUFFIXES):
        return FileKind.DATA_DEPLOY
    return FileKind.CODE


DELETED_FILE = "deleted.patch"


def render(records: List[FileDiff]) -> str:
    """The diff text a reviewer reads: noise left out, each deleted file collapsed to one marker."""
    parts = []
    for record in records:
        if record.kind is FileKind.NOISE:
            continue
        if record.status is FileStatus.DELETED:
            parts.append(f"diff --git a/{record.path} b/{record.path}\n"
                         f"(file deleted: {record.deleted} lines; the removed content is in {DELETED_FILE}"
                         f" in the review pack)\n")
        else:
            parts.append(record.text)
    return "".join(parts)


def render_deleted(records: List[FileDiff]) -> str:
    """The full removed content of every deleted file, for the reviewer that traces what still refers to it."""
    return "".join(record.text for record in records
                   if record.status is FileStatus.DELETED and record.kind is not FileKind.NOISE)


def review_lines(records: List[FileDiff]) -> int:
    return sum(record.review_lines for record in records)


def data_slice(records: List[FileDiff]) -> List[FileDiff]:
    return [record for record in records if record.kind is FileKind.DATA_DEPLOY]


def removes_or_renames(records: List[FileDiff]) -> bool:
    return any(record.status in (FileStatus.DELETED, FileStatus.RENAMED) for record in records
               if record.kind is not FileKind.NOISE)


def chunk(records: List[FileDiff], chunk_lines: int = CHUNK_LINES, max_chunks: int = MAX_CHUNKS) -> List[List[FileDiff]]:
    """Whole files grouped in diff order into at most `max_chunks` groups of about `chunk_lines` changed lines."""
    reviewable = [record for record in records if record.kind is not FileKind.NOISE]
    total = review_lines(reviewable)
    target = max(chunk_lines, math.ceil(total / max_chunks)) if total else chunk_lines
    groups: List[List[FileDiff]] = []
    current: List[FileDiff] = []
    size = 0
    for record in reviewable:
        if current and size + record.review_lines > target and len(groups) < max_chunks - 1:
            groups.append(current)
            current, size = [], 0
        current.append(record)
        size += record.review_lines
    if current:
        groups.append(current)
    return groups


def anchor_map(records: List[FileDiff]) -> Dict[str, List[Tuple[int, int]]]:
    """path -> new-side line ranges the diff shows. GitHub refuses an inline comment outside them."""
    return {record.path: [(hunk.new_start, hunk.new_end) for hunk in record.hunks]
            for record in records if record.hunks}
