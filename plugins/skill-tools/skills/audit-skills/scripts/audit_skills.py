#!/usr/bin/env python3
"""Mechanical checks for Claude Code skills against the 13 skill-writing rules.

Runs the checks a script can decide (line counts, link depth, contents lists,
description voice, path portability, reasoning-extraction phrases, ...) and
leaves judgment rules (3, 4, 8) to Claude. Each finding names the rule, the
file and line, what is wrong, and the fix.

Usage:
    audit_skills.py --all
    audit_skills.py --personal --plugins
    audit_skills.py ~/.claude/skills/my-skill .claude/skills
    audit_skills.py --all --only review-watch,create-issue --format json

Python 3.8+, standard library only.
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

SKILL_MD_MAX_LINES = 500
SKILL_MD_WARN_LINES = 400
CONTENTS_LIST_THRESHOLD = 100
CONTENTS_LIST_SEARCH_WINDOW = 30
MANY_STEPS_THRESHOLD = 4
TOP_OF_FILE_FRACTION = 0.4
DESCRIPTION_MAX_CHARS = 1024

TEXT_SUFFIXES = {".md", ".txt", ".markdown"}
SCRIPT_SUFFIXES = {".py", ".sh", ".js", ".ts", ".rb"}
IGNORED_NAMES = {"LICENSE", "LICENSE.md", ".gitignore", ".DS_Store"}
IGNORED_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv"}

KNOWN_CLI_TOOLS = {
    "gh", "jq", "curl", "docker", "npm", "npx", "node", "ffmpeg", "pandoc",
    "rg", "pdftotext", "convert", "magick", "aws", "gcloud", "kubectl", "uv",
}

MUST_HOLD_PATTERN = re.compile(r"\b(never|always|must)\b", re.IGNORECASE)
EMPHASIS_CAPS_PATTERN = re.compile(r"\b(MUST|NEVER|ALWAYS|IMPORTANT|CRITICAL|REQUIRED|FORBIDDEN|DO NOT|ONLY)\b")
LOCAL_MODULE_DIRS = ("shared", "lib", "scripts", "src")
LOCAL_MODULE_SEARCH_DEPTH = 3
GO_BACK_PATTERN = re.compile(
    r"\b(go back|return to step|back to step|repeat (from|step)|start (over|again)"
    r"|re-?run (from|step)|until (it|every|all|each) .*pass)", re.IGNORECASE)
CHECKLIST_PATTERN = re.compile(r"^\s*[-*]\s*\[[ xX]\]\s", re.MULTILINE)
NUMBERED_STEP_PATTERN = re.compile(r"^\s*(\d+)[.)]\s+\S")
CONTENTS_HEADING_PATTERN = re.compile(
    r"^(#{1,4}\s*|\*\*)?\s*(contents|table of contents|toc|in this (file|document|guide))\b",
    re.IGNORECASE)
REASONING_EXTRACTION_PATTERN = re.compile(
    r"think (step[- ]by[- ]step|aloud|out loud)"
    r"|(show|explain|write out|include|output|describe) (your|its|the) (reasoning|thinking|thought process|work)"
    r"|chain[- ]of[- ]thought"
    r"|reason(ing)? (out loud|aloud)"
    r"|<thinking>"
    r"|reflect on (your|the) (reasoning|answer)",
    re.IGNORECASE)
FIRST_PERSON_PATTERN = re.compile(r"\b(I|I'll|I'm|I've|we|we'll|our|my)\b")
QUOTED_TRIGGER_PATTERN = re.compile(r"\"[^\"]*\"|(?<!\w)'[^']*'(?!\w)")  # quoted trigger phrases, not apostrophes
SECOND_PERSON_PATTERN = re.compile(r"\b(you|you'll|your)\b", re.IGNORECASE)
PERSONAL_PATH_PATTERN = re.compile(r"(/home/[A-Za-z0-9_.-]+/|/Users/[A-Za-z0-9_.-]+/|[A-Za-z]:\\Users\\)")
BACKSLASH_PATH_PATTERN = re.compile(r"(?<![\\`])\b[A-Za-z0-9_.-]+\\[A-Za-z0-9_.-]+\\[A-Za-z0-9_.-]+")
GENERIC_ERROR_PATTERN = re.compile(
    r"""(print|exit|SystemExit|raise\s+\w+)\(\s*f?["'](error|failed|invalid|something went wrong|an error occurred)\.?["']\s*\)""",
    re.IGNORECASE)
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
INLINE_PATH_PATTERN = re.compile(r"`([^`\s]+/[^`\s]*|[^`\s/]+\.(?:md|py|sh|js|ts|json|yaml|yml|txt|csv))`")
BARE_PATH_PATTERN = re.compile(r"(?<![\w/])((?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]+)")
EVALS_HEADING_PATTERN = re.compile(r"^#{1,4}\s*.*\b(test prompts?|evals?|evaluations?|test (tasks|cases))\b", re.IGNORECASE)
EVALS_DIR_NAMES = {"evals", "eval", "tests", "test-prompts", "test_prompts"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    rule: int
    severity: str  # "fail" | "warn" | "info"
    file: str
    line: Optional[int]
    message: str
    fix: str

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "fix": self.fix,
        }


@dataclass
class Skill:
    name: str
    root: Path
    skill_md: Path
    frontmatter: Dict[str, str]
    body_lines: List[str]
    body_start_line: int
    files: List[Path] = field(default_factory=list)

    def relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def text_files(self) -> List[Path]:
        return [f for f in self.files if f.suffix.lower() in TEXT_SUFFIXES]

    def script_files(self) -> List[Path]:
        return [f for f in self.files if f.suffix.lower() in SCRIPT_SUFFIXES]


Checker = Callable[[Skill], List[Finding]]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def read_lines(path: Path) -> List[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        raise RuntimeError("Cannot read {}: {}".format(path, error))


def parse_frontmatter(lines: List[str]) -> Tuple[Dict[str, str], int]:
    """Return (frontmatter, body_start_line). Handles 'key: value' and folded
    multi-line values (indented continuation lines). Nested blocks such as
    'hooks:' are kept as their raw indented text."""
    if not lines or lines[0].strip() != "---":
        return {}, 1
    frontmatter: Dict[str, str] = {}
    current_key: Optional[str] = None
    for index in range(1, len(lines)):
        line = lines[index]
        if line.strip() == "---":
            return frontmatter, index + 2
        key_match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if key_match and not line.startswith((" ", "\t")):
            current_key = key_match.group(1)
            frontmatter[current_key] = key_match.group(2).strip()
        elif current_key is not None:
            frontmatter[current_key] = (frontmatter[current_key] + " " + line.strip()).strip()
    return frontmatter, len(lines) + 1


def collect_skill_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS and not d.startswith("."))
        for filename in sorted(filenames):
            if filename in IGNORED_NAMES or filename.startswith("."):
                continue
            path = Path(directory) / filename
            if (path.name == "SKILL.md" and path.parent == root) or not path.is_file():
                continue
            files.append(path)
    return files


def load_skill(skill_md: Path) -> Skill:
    root = skill_md.parent
    lines = read_lines(skill_md)
    frontmatter, body_start = parse_frontmatter(lines)
    body_lines = lines[body_start - 1:]
    name = frontmatter.get("name") or root.name
    return Skill(name=name, root=root, skill_md=skill_md, frontmatter=frontmatter,
                 body_lines=body_lines, body_start_line=body_start,
                 files=collect_skill_files(root))


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def find_skill_files_under(directory: Path, max_depth: int = 4) -> List[Path]:
    direct = directory / "SKILL.md"
    if direct.is_file():
        return [direct]
    found: List[Path] = []
    base_depth = len(directory.parts)
    for current, dirnames, filenames in os.walk(directory, followlinks=False):
        depth = len(Path(current).parts) - base_depth
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS and not d.startswith("."))
        if depth >= max_depth:
            dirnames[:] = []
        if "SKILL.md" in filenames:
            found.append(Path(current) / "SKILL.md")
            dirnames[:] = []
    return found


def personal_skill_dir() -> Path:
    return Path.home() / ".claude" / "skills"


def project_skill_dir() -> Path:
    return Path.cwd() / ".claude" / "skills"


def installed_plugin_paths() -> List[Path]:
    registry = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    if not registry.is_file():
        return []
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print("warning: cannot parse {}: {}".format(registry, error), file=sys.stderr)
        return []
    plugins = data.get("plugins", {})
    paths: List[Path] = []
    for entries in plugins.values():
        if isinstance(entries, dict):
            entries = [entries]
        for entry in entries:
            install_path = entry.get("installPath") if isinstance(entry, dict) else None
            if install_path:
                paths.append(Path(install_path))
    return paths


def discover(args: argparse.Namespace) -> List[Path]:
    roots: List[Path] = []
    if args.all or args.personal:
        roots.append(personal_skill_dir())
    if args.all or args.project:
        roots.append(project_skill_dir())
    if args.all or args.plugins:
        roots.extend(installed_plugin_paths())
    roots.extend(Path(p).expanduser() for p in args.paths)

    skill_files: List[Path] = []
    seen: Set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for skill_md in find_skill_files_under(root):
            resolved = skill_md.resolve()
            if resolved not in seen:
                seen.add(resolved)
                skill_files.append(skill_md)
    return skill_files


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def strip_code_fences(lines: List[str]) -> List[Tuple[int, str]]:
    """Yield (1-based line number, text) for lines outside fenced code blocks."""
    result: List[Tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(lines, start=1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            result.append((number, line))
    return result


def fenced_code_lines(lines: List[str]) -> List[Tuple[int, str]]:
    result: List[Tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(lines, start=1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            result.append((number, line))
    return result


def referenced_paths(text: str) -> Set[str]:
    refs: Set[str] = set()
    for pattern in (MARKDOWN_LINK_PATTERN, INLINE_PATH_PATTERN, BARE_PATH_PATTERN):
        for match in pattern.finditer(text):
            candidate = match.group(1).strip()
            if candidate.startswith(("http://", "https://", "mailto:", "#")):
                continue
            while candidate.startswith("./"):
                candidate = candidate[2:]
            refs.add(candidate)
    return refs


def resolve_reference(skill: Skill, reference: str) -> Optional[Path]:
    candidate = (skill.root / reference).resolve()
    if candidate.exists():
        return candidate
    return None


def links_from(skill: Skill, path: Path) -> Set[Path]:
    """Files or directories inside the skill folder that `path` references."""
    targets: Set[Path] = set()
    for reference in referenced_paths("\n".join(read_lines(path))):
        resolved = resolve_reference(skill, reference)
        if resolved is not None and skill.root.resolve() in resolved.parents:
            targets.add(resolved)
    return targets


def is_covered(target: Path, linked: Set[Path]) -> bool:
    resolved = target.resolve()
    if resolved in linked:
        return True
    return any(link.is_dir() and link in resolved.parents for link in linked)


def has_contents_list(lines: List[str], body_start: int = 1) -> bool:
    window = lines[body_start - 1: body_start - 1 + CONTENTS_LIST_SEARCH_WINDOW]
    return any(CONTENTS_HEADING_PATTERN.match(line.strip()) for line in window)


def stdlib_module_names() -> Set[str]:
    names = getattr(sys, "stdlib_module_names", None)
    if names:
        return set(names)
    return {
        "os", "sys", "re", "json", "argparse", "pathlib", "typing", "dataclasses",
        "subprocess", "datetime", "time", "collections", "itertools", "functools",
        "shutil", "tempfile", "logging", "urllib", "http", "base64", "hashlib",
        "textwrap", "csv", "io", "math", "random", "string", "enum", "abc",
    }


def third_party_imports(script: Path) -> Set[str]:
    stdlib = stdlib_module_names()
    found: Set[str] = set()
    for line in read_lines(script):
        match = re.match(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", line)
        if not match:
            continue
        module = (match.group(1) or match.group(2)).split(".")[0]
        if module not in stdlib and not module.startswith("_"):
            found.add(module)
    return found


def local_modules(skill: Skill) -> Set[str]:
    """Module names resolvable from the skill folder or a nearby plugin folder
    (e.g. a plugin-level shared/ directory added to sys.path by the script)."""
    names = {f.stem for f in skill.files if f.suffix == ".py"}
    names |= {d.name for d in skill.root.rglob("*") if d.is_dir()}
    ancestor = skill.root
    for _ in range(LOCAL_MODULE_SEARCH_DEPTH):
        ancestor = ancestor.parent
        for directory in (ancestor,) + tuple(ancestor / name for name in LOCAL_MODULE_DIRS):
            if directory.is_dir():
                names |= {f.stem for f in directory.glob("*.py")}
                names |= {d.name for d in directory.iterdir() if (d / "__init__.py").is_file()}
    return names


# ---------------------------------------------------------------------------
# Rule checkers (one per rule the script can decide)
# ---------------------------------------------------------------------------

def check_rule_1_progressive_disclosure(skill: Skill) -> List[Finding]:
    findings: List[Finding] = []
    body_count = len(skill.body_lines)
    if body_count > SKILL_MD_MAX_LINES:
        findings.append(Finding(1, "fail", "SKILL.md", skill.body_start_line,
                                "SKILL.md body is {} lines (limit {})".format(body_count, SKILL_MD_MAX_LINES),
                                "Move detail only some jobs need into references/<topic>.md and link it from SKILL.md"))
    elif body_count > SKILL_MD_WARN_LINES:
        findings.append(Finding(1, "warn", "SKILL.md", skill.body_start_line,
                                "SKILL.md body is {} lines, near the {} limit".format(body_count, SKILL_MD_MAX_LINES),
                                "Plan to split sections that only some jobs need into their own files"))

    direct_links = links_from(skill, skill.skill_md)
    secondary_links: Dict[Path, Path] = {}
    for text_file in skill.text_files():
        for target in links_from(skill, text_file):
            secondary_links.setdefault(target.resolve(), text_file)

    for candidate in skill.files:
        resolved = candidate.resolve()
        if is_covered(candidate, direct_links):
            continue
        relative = skill.relative(candidate)
        if resolved in secondary_links:
            via = skill.relative(secondary_links[resolved])
            findings.append(Finding(1, "fail", relative, None,
                                    "Only reachable through {} (nested reference, may be previewed with head -100)".format(via),
                                    "Link {} directly from SKILL.md, or fold it into {}".format(relative, via)))
        else:
            findings.append(Finding(1, "warn", relative, None,
                                    "Not linked from SKILL.md or any other file",
                                    "Link it from SKILL.md with a one-line note on when to read it, or delete it"))
    return findings


def check_rule_2_contents_lists(skill: Skill) -> List[Finding]:
    findings: List[Finding] = []
    candidates = [(skill.skill_md, skill.body_start_line)] + [(f, 1) for f in skill.text_files()]
    for path, body_start in candidates:
        lines = read_lines(path)
        count = len(lines) - (body_start - 1)
        if count > CONTENTS_LIST_THRESHOLD and not has_contents_list(lines, body_start):
            severity = "warn" if path == skill.skill_md else "fail"
            findings.append(Finding(2, severity, skill.relative(path), body_start,
                                    "{} lines with no contents list in the first {} lines".format(count, CONTENTS_LIST_SEARCH_WINDOW),
                                    "Add a '## Contents' heading at the top with one line per section, in file order"))
    return findings


def unquote_yaml_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def check_rule_5_description(skill: Skill) -> List[Finding]:
    findings: List[Finding] = []
    description = unquote_yaml_scalar(skill.frontmatter.get("description", ""))
    if not skill.frontmatter:
        return [Finding(5, "fail", "SKILL.md", 1, "No YAML frontmatter found",
                        "Add frontmatter with name and a third-person description of what the skill does and when to use it")]
    if not description:
        return [Finding(5, "fail", "SKILL.md", 1, "Frontmatter has no description",
                        "Add 'description:' saying what the skill does and when to use it, in the third person")]
    prose = QUOTED_TRIGGER_PATTERN.sub("", description)
    if FIRST_PERSON_PATTERN.search(prose):
        findings.append(Finding(5, "fail", "SKILL.md", 2,
                                "Description uses first person: {!r}".format(FIRST_PERSON_PATTERN.search(prose).group(0)),
                                "Rewrite in third person: 'Creates X and does Y. Use when ...'"))
    if SECOND_PERSON_PATTERN.search(prose):
        findings.append(Finding(5, "warn", "SKILL.md", 2,
                                "Description addresses the reader as 'you'",
                                "Rewrite in third person; describe the skill, not the reader"))
    if len(description) > DESCRIPTION_MAX_CHARS:
        findings.append(Finding(5, "warn", "SKILL.md", 2,
                                "Description is {} characters (over {})".format(len(description), DESCRIPTION_MAX_CHARS),
                                "Shorten to what the skill does plus the trigger phrases"))
    if not re.search(r"\b(use when|when the user|when asked|when you need|trigger|for requests)\b", description, re.IGNORECASE):
        findings.append(Finding(5, "warn", "SKILL.md", 2,
                                "Description does not say when to use the skill",
                                "Add 'Use when ...' with the phrases a user would say"))
    return findings


def longest_numbered_run(lines: List[str]) -> Tuple[int, Optional[int]]:
    longest, start_of_longest = 0, None
    current, start_of_current, expected = 0, None, 1
    for number, line in enumerate(lines, start=1):
        match = NUMBERED_STEP_PATTERN.match(line)
        if match and int(match.group(1)) == expected:
            if current == 0:
                start_of_current = number
            current += 1
            expected += 1
        elif match and int(match.group(1)) == 1:
            current, start_of_current, expected = 1, number, 2
        elif line.strip() and not line.startswith((" ", "\t", "-", "*")):
            if current > longest:
                longest, start_of_longest = current, start_of_current
            current, start_of_current, expected = 0, None, 1
    if current > longest:
        longest, start_of_longest = current, start_of_current
    return longest, start_of_longest


def check_rule_6_workflows(skill: Skill) -> List[Finding]:
    steps, start = longest_numbered_run(skill.body_lines)
    if steps <= MANY_STEPS_THRESHOLD:
        return []
    body_text = "\n".join(skill.body_lines)
    line = skill.body_start_line + (start or 1) - 1
    findings: List[Finding] = []
    if not CHECKLIST_PATTERN.search(body_text):
        findings.append(Finding(6, "fail", "SKILL.md", line,
                                "{}-step workflow with no copyable '- [ ]' checklist".format(steps),
                                "Add 'Copy this checklist and track progress:' followed by one '- [ ] Step N' line per step"))
    if not GO_BACK_PATTERN.search(body_text):
        findings.append(Finding(6, "fail", "SKILL.md", line,
                                "{}-step workflow with no go-back line after checks".format(steps),
                                "Under each verification step add 'If the check fails, go back to Step N'"))
    return findings


def check_rule_7_error_messages(skill: Skill) -> List[Finding]:
    findings: List[Finding] = []
    for script in skill.script_files():
        for number, line in enumerate(read_lines(script), start=1):
            if GENERIC_ERROR_PATTERN.search(line):
                findings.append(Finding(7, "warn", skill.relative(script), number,
                                        "Generic error message: {}".format(line.strip()[:80]),
                                        "Name what broke and what exists, e.g. \"Field 'x' not found. Available: a, b, c\""))
    return findings


def check_rule_9_shareability(skill: Skill) -> List[Finding]:
    findings: List[Finding] = []
    skill_text = "\n".join(skill.body_lines)
    for path in [skill.skill_md] + skill.text_files():
        for number, line in strip_code_fences(read_lines(path)):
            if PERSONAL_PATH_PATTERN.search(line):
                findings.append(Finding(9, "fail", skill.relative(path), number,
                                        "Path only exists on one machine: {}".format(PERSONAL_PATH_PATTERN.search(line).group(0)),
                                        "Use a path inside the skill folder, ~ for home, or an environment variable"))
            if BACKSLASH_PATH_PATTERN.search(line):
                findings.append(Finding(9, "fail", skill.relative(path), number,
                                        "Backslash path: {}".format(BACKSLASH_PATH_PATTERN.search(line).group(0)),
                                        "Use forward slashes so the skill works on every platform"))
    resolvable = local_modules(skill)
    for script in [f for f in skill.script_files() if f.suffix == ".py"]:
        for module in sorted(third_party_imports(script) - resolvable):
            if not re.search(r"(pip install|requirements|needs|prerequisite|install)[^\n]*\b{}\b".format(re.escape(module)),
                             skill_text, re.IGNORECASE):
                findings.append(Finding(9, "fail", skill.relative(script), None,
                                        "Imports '{}' but SKILL.md has no install line for it".format(module),
                                        "Add to SKILL.md: 'Needs: pip install {}'".format(module)))
    tools_used = set()
    for _, line in fenced_code_lines(skill.body_lines):
        first_word = line.strip().split(" ")[0] if line.strip() else ""
        if first_word in KNOWN_CLI_TOOLS:
            tools_used.add(first_word)
    has_needs_section = re.search(r"^#{1,4}\s*(needs|requirements?|prerequisites?|dependencies|setup)\b",
                                  skill_text, re.IGNORECASE | re.MULTILINE)
    for tool in sorted(tools_used):
        if not has_needs_section and not re.search(r"(install|requires?|needs)[^\n]*\b{}\b".format(re.escape(tool)), skill_text, re.IGNORECASE):
            findings.append(Finding(9, "warn", "SKILL.md", None,
                                    "Uses CLI tool '{}' without naming it as a requirement".format(tool),
                                    "Add a short 'Needs' list naming {} and how to install it".format(tool)))
    return findings


def check_rule_10_must_hold_rules(skill: Skill) -> List[Finding]:
    hits: List[Tuple[int, str]] = []
    for number, line in strip_code_fences(skill.body_lines):
        if MUST_HOLD_PATTERN.search(line) or EMPHASIS_CAPS_PATTERN.search(line):
            hits.append((skill.body_start_line + number - 1, line.strip()))
    if not hits:
        return []
    has_hooks = "hooks" in skill.frontmatter
    sample = "; ".join("L{}: {}".format(n, text[:60]) for n, text in hits[:5])
    severity = "info" if has_hooks else "warn"
    return [Finding(10, severity, "SKILL.md", hits[0][0],
                    "{} must-hold phrase(s) (never/always/must/IMPORTANT){}. First: {}".format(
                        len(hits), "" if has_hooks else ", no hooks frontmatter", sample),
                    "For each, ask what one miss costs. Move the costly ones into a hooks: frontmatter entry "
                    "and say which event (PreToolUse, PostToolUse, Stop) runs it; keep the rest as plain words with the reason")]


def check_rule_11_test_prompts(skill: Skill) -> List[Finding]:
    has_dir = any(part in EVALS_DIR_NAMES for f in skill.files for part in f.relative_to(skill.root).parts[:-1])
    has_file = any(re.match(r"^(evals?|test[-_]?prompts?|tests?)\.(md|json|yaml|yml|txt)$", f.name, re.IGNORECASE)
                   for f in skill.files)
    has_heading = any(EVALS_HEADING_PATTERN.match(line) for path in [skill.skill_md] + skill.text_files()
                      for line in read_lines(path))
    if has_dir or has_file or has_heading:
        return []
    return [Finding(11, "fail", "SKILL.md", None,
                    "No test prompts found (no evals/ folder, evals file, or 'Test prompts' section)",
                    "Add evals/evals.json or a 'Test prompts' section with three real prompts, "
                    "and note the baseline result without the skill")]


def check_rule_12_important_first(skill: Skill) -> List[Finding]:
    body = strip_code_fences(skill.body_lines)
    if len(body) < 40:
        return []
    first_rule_line = next((number for number, line in body if MUST_HOLD_PATTERN.search(line)), None)
    if first_rule_line is None:
        return []
    position = first_rule_line / max(len(skill.body_lines), 1)
    if position <= TOP_OF_FILE_FRACTION:
        return []
    return [Finding(12, "warn", "SKILL.md", skill.body_start_line + first_rule_line - 1,
                    "First must-hold instruction appears {:.0%} of the way down SKILL.md".format(position),
                    "Move the rules that must never be missed into the first screen of SKILL.md; "
                    "push background and long examples lower or into their own files")]


def check_rule_13_no_reasoning_extraction(skill: Skill) -> List[Finding]:
    findings: List[Finding] = []
    for path in [skill.skill_md] + skill.text_files():
        for number, line in enumerate(read_lines(path), start=1):
            match = REASONING_EXTRACTION_PATTERN.search(line)
            if match:
                findings.append(Finding(13, "fail", skill.relative(path), number,
                                        "Asks Claude to write out its reasoning: {!r}".format(match.group(0)),
                                        "Ask for the answer plus a short explanation instead"))
    return findings


CHECKERS: List[Checker] = [
    check_rule_1_progressive_disclosure,
    check_rule_2_contents_lists,
    check_rule_5_description,
    check_rule_6_workflows,
    check_rule_7_error_messages,
    check_rule_9_shareability,
    check_rule_10_must_hold_rules,
    check_rule_11_test_prompts,
    check_rule_12_important_first,
    check_rule_13_no_reasoning_extraction,
]

JUDGMENT_RULES = {
    3: "Degrees of freedom: costly steps locked to exact commands, simple steps left open",
    4: "Model fit: instructions not over-prescriptive for the model that runs the skill",
    8: "Common patterns: templates say strict or default, style output has examples, branches have a fork",
}


# ---------------------------------------------------------------------------
# Running and reporting
# ---------------------------------------------------------------------------

@dataclass
class SkillReport:
    skill: Skill
    findings: List[Finding]

    def count(self, severity: str) -> int:
        return sum(1 for f in self.findings if f.severity == severity)

    def worst(self) -> str:
        for severity in ("fail", "warn", "info"):
            for finding in self.findings:
                if finding.severity == severity:
                    return "R{}: {}".format(finding.rule, finding.message)
        return "none"

    def to_dict(self) -> dict:
        return {
            "name": self.skill.name,
            "path": str(self.skill.root),
            "fails": self.count("fail"),
            "warns": self.count("warn"),
            "findings": [f.to_dict() for f in self.findings],
        }


SEVERITY_ORDER = {"fail": 0, "warn": 1, "info": 2}


def audit(skill: Skill) -> SkillReport:
    findings: List[Finding] = []
    for checker in CHECKERS:
        findings.extend(checker(skill))
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule, f.file, f.line or 0))
    return SkillReport(skill=skill, findings=findings)


def render_markdown(reports: List[SkillReport], summary_only: bool) -> str:
    out: List[str] = ["| Skill | Path | Fails | Warns | Worst problem |", "|---|---|---|---|---|"]
    for report in sorted(reports, key=lambda r: (-r.count("fail"), -r.count("warn"), r.skill.name)):
        out.append("| {} | {} | {} | {} | {} |".format(
            report.skill.name, report.skill.root, report.count("fail"), report.count("warn"),
            report.worst().replace("|", "\\|")))
    if summary_only:
        return "\n".join(out)
    for report in reports:
        out.append("")
        out.append("## {}  ({})".format(report.skill.name, report.skill.root))
        if not report.findings:
            out.append("No mechanical findings. Judgment rules {} still need a read.".format(
                ", ".join(str(r) for r in JUDGMENT_RULES)))
            continue
        for finding in report.findings:
            location = finding.file + (":{}".format(finding.line) if finding.line else "")
            out.append("- [{}] R{} {} — {}. Fix: {}".format(
                finding.severity.upper(), finding.rule, location, finding.message, finding.fix))
    out.append("")
    out.append("Judgment rules (not checked by this script): " + "; ".join(
        "R{} {}".format(rule, text) for rule, text in JUDGMENT_RULES.items()))
    return "\n".join(out)


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", help="skill folders or folders containing skills")
    parser.add_argument("--all", action="store_true", help="personal + project + installed plugin skills")
    parser.add_argument("--personal", action="store_true", help="~/.claude/skills")
    parser.add_argument("--project", action="store_true", help="./.claude/skills")
    parser.add_argument("--plugins", action="store_true", help="skills inside installed plugins")
    parser.add_argument("--only", default="", help="comma-separated skill names to include")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--summary", action="store_true", help="print only the summary table")
    args = parser.parse_args(argv)
    if not (args.all or args.personal or args.project or args.plugins or args.paths):
        parser.error("Nothing to audit. Pass --all, --personal, --project, --plugins, or one or more paths.")
    return args


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    skill_files = discover(args)
    if not skill_files:
        print("No SKILL.md files found in the requested locations.", file=sys.stderr)
        return 2
    wanted = {name.strip() for name in args.only.split(",") if name.strip()}
    reports: List[SkillReport] = []
    for skill_md in skill_files:
        try:
            skill = load_skill(skill_md)
            if wanted and skill.name not in wanted and skill.root.name not in wanted:
                continue
            reports.append(audit(skill))
        except RuntimeError as error:
            print("warning: {}".format(error), file=sys.stderr)
    if not reports:
        print("No skills matched --only {}".format(sorted(wanted)), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps([r.to_dict() for r in reports], indent=2))
    else:
        print(render_markdown(reports, args.summary))
    return 1 if any(r.count("fail") for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
