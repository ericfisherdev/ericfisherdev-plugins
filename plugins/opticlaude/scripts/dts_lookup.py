#!/usr/bin/env python3
"""Print exact declaration blocks from a TypeScript .d.ts (or any .ts) file.

    dts_lookup.py FILE NAME [NAME ...]       declaration(s) named NAME, with doc comment
    dts_lookup.py FILE -g REGEX              one line per declaration whose line matches REGEX
    dts_lookup.py FILE NAME --no-doc         skip the leading JSDoc block
    dts_lookup.py FILE NAME --max 10         cap matches per name (default 5)

NAME matches `export type|interface|class|function|const|enum|namespace NAME`,
`declare module 'NAME'`, and member-style entries such as `'session.start': {`
or `foo(`. Blocks end when brackets balance and no continuation follows, so a
multi-line union type is returned whole. Output lines carry their real line
numbers so follow-up edits can anchor on them.
"""
from __future__ import annotations

import argparse
import re
import sys

KINDS = r"(?:abstract\s+)?(?:async\s+)?(?:type|interface|class|function|const|let|var|enum|namespace|module)"
DECL_PREFIX = r"^(?P<indent>\s*)(?:export\s+)?(?:default\s+)?(?:declare\s+)?"
GENERIC_DECL = re.compile(DECL_PREFIX + KINDS + r"\s+(?P<name>[A-Za-z_$][\w$]*)")
CONTINUATION_END = re.compile(r"(=|\||&|,|\(|<|extends|implements|=>|\?|:)\s*$")
CONTINUATION_START = re.compile(r"^\s*(\||&|\?|:|\.|\)|extends|implements)")
OPEN, CLOSE = "{[(", "}])"


def declaration_patterns(name: str) -> list[re.Pattern[str]]:
    escaped = re.escape(name)
    return [
        re.compile(DECL_PREFIX + KINDS + r"\s+" + escaped + r"\b"),
        re.compile(r"^\s*declare\s+module\s+['\"]" + escaped + r"['\"]"),
        re.compile(r"^\s*(?:readonly\s+|static\s+|public\s+|private\s+|protected\s+)*['\"]?" + escaped + r"['\"]?\??\s*[:(<]"),
    ]


def strip_code(line: str, in_block_comment: bool) -> tuple[str, bool]:
    """Remove strings and comments so bracket counting ignores them."""
    out: list[str] = []
    i = 0
    quote: str | None = None
    while i < len(line):
        ch = line[i]
        nxt = line[i + 1] if i + 1 < len(line) else ""
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch == "/" and nxt == "/":
            break
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch in "'\"`":
            quote = ch
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out), in_block_comment


def block_end(lines: list[str], start: int) -> int:
    depth = 0
    in_comment = False
    for index in range(start, len(lines)):
        code, in_comment = strip_code(lines[index], in_comment)
        depth += sum(code.count(c) for c in OPEN) - sum(code.count(c) for c in CLOSE)
        if depth > 0 or in_comment:
            continue
        stripped = code.strip()
        next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if CONTINUATION_END.search(stripped) or CONTINUATION_START.match(next_line):
            continue
        return index
    return len(lines) - 1


def doc_start(lines: list[str], decl: int) -> int:
    index = decl - 1
    while index >= 0 and lines[index].strip().startswith(("*", "/**", "//", "*/")):
        if lines[index].strip().startswith("/**") or lines[index].strip().startswith("/*"):
            return index
        index -= 1
    return decl


def find_blocks(lines: list[str], name: str, include_doc: bool, limit: int) -> list[tuple[int, int]]:
    patterns = declaration_patterns(name)
    found: list[tuple[int, int]] = []
    for number, line in enumerate(lines):
        if not any(p.match(line) for p in patterns):
            continue
        start = doc_start(lines, number) if include_doc else number
        found.append((start, block_end(lines, number)))
        if len(found) >= limit:
            break
    return found


def print_block(path: str, lines: list[str], start: int, end: int, label: str) -> None:
    print(f"--- {path}:{start + 1}-{end + 1} {label}")
    width = len(str(end + 1))
    for number in range(start, end + 1):
        print(f"{number + 1:>{width}}: {lines[number].rstrip()}")


def grep_declarations(path: str, lines: list[str], regex: str) -> int:
    pattern = re.compile(regex)
    hits = 0
    for number, line in enumerate(lines):
        if GENERIC_DECL.match(line) and pattern.search(line):
            print(f"{number + 1}: {line.strip().rstrip('{').rstrip()}")
            hits += 1
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("names", nargs="*")
    ap.add_argument("-g", "--grep", help="regex over declaration lines; lists line numbers")
    ap.add_argument("--no-doc", action="store_true", help="omit the JSDoc block above the declaration")
    ap.add_argument("--max", type=int, default=5, help="max matches per name")
    args = ap.parse_args()
    if not args.names and not args.grep:
        ap.error("give at least one NAME or -g REGEX")

    with open(args.file, encoding="utf-8") as fh:
        lines = fh.read().split("\n")

    missing = 0
    if args.grep and grep_declarations(args.file, lines, args.grep) == 0:
        print(f"no declaration matches /{args.grep}/", file=sys.stderr)
        missing += 1
    for name in args.names:
        blocks = find_blocks(lines, name, not args.no_doc, args.max)
        if not blocks:
            print(f"not found: {name}", file=sys.stderr)
            missing += 1
            continue
        for start, end in blocks:
            print_block(args.file, lines, start, end, name)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
