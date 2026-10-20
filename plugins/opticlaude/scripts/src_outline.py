#!/usr/bin/env python3
"""Symbol outline of source files, or a blank-stripped numbered dump.

    src_outline.py PATH [PATH ...]            outline: imports summary + symbols with line numbers
    src_outline.py PATH --dump                full text, blank lines removed, real line numbers kept
    src_outline.py FILE --dump -l 120-180     one line range
    src_outline.py DIR --ext ts,tsx           restrict extensions when walking a directory

Outline covers TypeScript/JavaScript, Python, Go, Rust, PHP, Java, Kotlin, C#.
Other extensions get a line count only. Use the outline to orient, then dump
or read only the ranges that matter.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Iterable

DEFAULT_EXTS = {"ts", "tsx", "js", "jsx", "mjs", "cjs", "py", "go", "rs", "php", "java", "kt", "cs"}
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "target", "vendor", "__pycache__", ".venv", "venv", "coverage"}
MAX_WIDTH = 120

TS_KEYWORDS = {"if", "for", "while", "switch", "catch", "else", "return", "new", "await", "typeof", "function", "super"}
TS_TOP = re.compile(
    r"^(?P<indent>\s*)(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?"
    r"(?:class|interface|type|enum|function\*?|namespace|module)\s+[A-Za-z_$][\w$]*"
)
TS_TOP_VALUE = re.compile(r"^(?:export\s+)?(?:declare\s+)?(?:const|let|var)\s+[A-Za-z_$][\w$]*")
TS_MEMBER = re.compile(
    r"^(?P<indent>\s+)(?:(?:public|private|protected|static|readonly|abstract|override|async|get|set)\s+)*"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\([^)]*\)?\s*(?::\s*[^{;]+)?\s*(?:\{|$)"
)
PY_DEF = re.compile(r"^(?P<indent>\s*)(?:async\s+)?(?:def|class)\s+\w+")
GO_DEF = re.compile(r"^(?:func|type|var|const)\s+(?:\([^)]*\)\s*)?\w+")
RS_DEF = re.compile(r"^(?P<indent>\s*)(?:pub(?:\([^)]*\))?\s+)?(?:async\s+|unsafe\s+|const\s+)*(?:fn|struct|enum|trait|impl|mod|type|const|static|macro_rules!)\s+")
PHP_DEF = re.compile(r"^(?P<indent>\s*)(?:(?:abstract|final|public|private|protected|static|readonly)\s+)*(?:class|interface|trait|enum|function)\s+\w+")
JVM_DEF = re.compile(
    r"^(?P<indent>\s*)(?:(?:public|private|protected|internal|static|final|abstract|open|override|suspend|sealed|data|async|partial|virtual|inline)\s+)*"
    r"(?:class|interface|enum|object|record|struct|fun|void|[A-Z][\w<>\[\], ]*)\s+\w+\s*(?:\(|\{|<|:|$)"
)
IMPORT = {
    "ts": re.compile(r"^\s*import\b.*?from\s+['\"]([^'\"]+)['\"]|^\s*import\s+['\"]([^'\"]+)['\"]"),
    "py": re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))"),
    "go": re.compile(r"^\s*\"([^\"]+)\"\s*$|^import\s+\"([^\"]+)\""),
    "rs": re.compile(r"^\s*use\s+([\w:]+)"),
    "php": re.compile(r"^\s*use\s+([\w\\]+)"),
    "jvm": re.compile(r"^\s*(?:import|using)\s+([\w.]+)"),
}
FAMILY = {
    "ts": "ts", "tsx": "ts", "js": "ts", "jsx": "ts", "mjs": "ts", "cjs": "ts",
    "py": "py", "go": "go", "rs": "rs", "php": "php", "java": "jvm", "kt": "jvm", "cs": "jvm",
}


def walk(paths: Iterable[str], exts: set[str]) -> list[str]:
    files: list[str] = []
    for path in paths:
        if os.path.isdir(path):
            for root, dirs, names in os.walk(path):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                files.extend(os.path.join(root, n) for n in sorted(names) if n.rsplit(".", 1)[-1] in exts)
        elif os.path.isfile(path):
            files.append(path)
        else:
            print(f"not found: {path}", file=sys.stderr)
    return files


def family_of(path: str) -> str | None:
    return FAMILY.get(path.rsplit(".", 1)[-1].lower())


def symbol_line(family: str, line: str) -> bool:
    if family == "ts":
        if TS_TOP.match(line) or TS_TOP_VALUE.match(line):
            return True
        member = TS_MEMBER.match(line)
        return bool(member and member.group("name") not in TS_KEYWORDS and not line.lstrip().startswith(("//", "*", "return")))
    if family == "py":
        return bool(PY_DEF.match(line))
    if family == "go":
        return bool(GO_DEF.match(line))
    if family == "rs":
        return bool(RS_DEF.match(line))
    if family == "php":
        return bool(PHP_DEF.match(line))
    if family == "jvm":
        return bool(JVM_DEF.match(line)) and not line.lstrip().startswith(("return", "new ", "else", "throw"))
    return False


def imports_of(family: str, lines: list[str]) -> list[str]:
    pattern = IMPORT.get(family)
    if not pattern:
        return []
    found: list[str] = []
    for line in lines:
        match = pattern.match(line)
        if match:
            found.append(next(g for g in match.groups() if g))
    return found


def compact(line: str) -> str:
    text = line.rstrip().rstrip("{").rstrip()
    indent = len(line) - len(line.lstrip())
    text = " " * (indent // 2) + text.lstrip()
    return text if len(text) <= MAX_WIDTH else text[: MAX_WIDTH - 1] + "…"


def outline(path: str, lines: list[str]) -> None:
    family = family_of(path)
    print(f"== {path} ({len(lines)} lines)")
    if not family:
        return
    imports = imports_of(family, lines)
    if imports:
        print(f"  imports: {', '.join(imports)}")
    width = len(str(len(lines)))
    for number, line in enumerate(lines, 1):
        if symbol_line(family, line):
            print(f"  {number:>{width}}  {compact(line)}")


def dump(path: str, lines: list[str], line_range: tuple[int, int] | None) -> None:
    start, end = line_range or (1, len(lines))
    print(f"== {path} {start}-{min(end, len(lines))}")
    width = len(str(end))
    for number in range(start, min(end, len(lines)) + 1):
        text = lines[number - 1].rstrip()
        if text:
            print(f"{number:>{width}}: {text}")


def parse_range(spec: str | None) -> tuple[int, int] | None:
    if not spec:
        return None
    start, _, end = spec.partition("-")
    return int(start), int(end or start)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--dump", action="store_true", help="print content with blank lines removed")
    ap.add_argument("-l", "--lines", help="line range A-B for --dump (single file)")
    ap.add_argument("--ext", help="comma-separated extensions when walking directories")
    args = ap.parse_args()

    exts = set(args.ext.split(",")) if args.ext else DEFAULT_EXTS
    files = walk(args.paths, exts)
    if not files:
        return 1
    line_range = parse_range(args.lines)
    for path in files:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        if args.dump:
            dump(path, lines, line_range)
        else:
            outline(path, lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
