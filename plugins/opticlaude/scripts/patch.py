#!/usr/bin/env python3
"""Apply anchored string replacements to files from a compact hunk spec.

Spec (stdin, or a file via -f):

    @@ path/to/file
    old text (must occur exactly once)
    ===
    new text
    @@* other/file          (`@@*` = replace every occurrence, at least one)
    old
    ===
    new

A hunk ends at the next `@@` header or end of input. An empty new block deletes
the old text. Content lines that would collide with the markers are escaped
with a leading backslash: `\\@@ ...` or `\\===`.

Every hunk is validated against the in-memory file state before anything is
written, so a run is all-or-nothing. Hunks on the same file apply in order.
Exit status 1 on any failure, with one `FAIL` line per bad hunk.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

HEADER = "@@"
DEFAULT_SEP = "==="


@dataclass
class Hunk:
    path: str
    replace_all: bool
    old: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)
    index: int = 0

    @property
    def old_text(self) -> str:
        return "\n".join(self.old)

    @property
    def new_text(self) -> str:
        return "\n".join(self.new)


class SpecError(Exception):
    pass


def unescape(line: str) -> str:
    if line.startswith("\\" + HEADER) or line.startswith("\\" + DEFAULT_SEP):
        return line[1:]
    return line


def parse(spec: str, sep: str) -> list[Hunk]:
    hunks: list[Hunk] = []
    current: Hunk | None = None
    in_new = False
    for raw in spec.split("\n"):
        if raw.startswith(HEADER + " ") or raw.startswith(HEADER + "* "):
            replace_all = raw.startswith(HEADER + "* ")
            path = raw[len(HEADER) + (2 if replace_all else 1):].strip()
            if not path:
                raise SpecError("header without path")
            current = Hunk(path=path, replace_all=replace_all, index=len(hunks) + 1)
            hunks.append(current)
            in_new = False
            continue
        if current is None:
            if raw.strip():
                raise SpecError(f"text before first header: {raw!r}")
            continue
        if raw == sep and not in_new:
            in_new = True
            continue
        (current.new if in_new else current.old).append(unescape(raw))
    for hunk in hunks:
        strip_trailing_blank(hunk.old)
        strip_trailing_blank(hunk.new)
        if not hunk.old_text:
            raise SpecError(f"hunk {hunk.index} ({hunk.path}): empty old block")
    return hunks


def strip_trailing_blank(lines: list[str]) -> None:
    """Drop the single empty line that precedes a marker or end of input."""
    if lines and lines[-1] == "":
        lines.pop()


def newline_style(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def closest_line(content: str, hunk: Hunk) -> str:
    anchor = next((l.strip() for l in hunk.old if l.strip()), "")
    if not anchor:
        return ""
    for number, line in enumerate(content.split("\n"), 1):
        if anchor in line:
            return f"; first old line found at line {number}"
    return "; no line of the old block found"


def apply(hunk: Hunk, content: str) -> tuple[str, str]:
    """Return (new content, report line). Raises SpecError on mismatch."""
    nl = newline_style(content)
    old = hunk.old_text.replace("\n", nl)
    new = hunk.new_text.replace("\n", nl)
    count = content.count(old)
    if count == 0:
        raise SpecError(f"old text not found{closest_line(content, hunk)}")
    if count > 1 and not hunk.replace_all:
        raise SpecError(f"{count} matches, expected exactly one (use @@* to replace all)")
    first_line = content[: content.index(old)].count(nl) + 1
    updated = content.replace(old, new)
    tag = f"x{count}" if hunk.replace_all else ""
    return updated, f"ok {hunk.path}:{first_line} -{len(hunk.old)} +{len(hunk.new)} {tag}".rstrip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-f", "--file", help="read the spec from this file instead of stdin")
    ap.add_argument("-n", "--dry-run", action="store_true", help="validate and report, write nothing")
    ap.add_argument("--sep", default=DEFAULT_SEP, help=f"old/new separator line (default {DEFAULT_SEP})")
    args = ap.parse_args()

    spec = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
    try:
        hunks = parse(spec, args.sep)
    except SpecError as err:
        print(f"FAIL spec: {err}", file=sys.stderr)
        return 1
    if not hunks:
        print("FAIL spec: no hunks", file=sys.stderr)
        return 1

    contents: dict[str, str] = {}
    reports: list[str] = []
    failures: list[str] = []
    for hunk in hunks:
        if hunk.path not in contents:
            try:
                with open(hunk.path, encoding="utf-8", newline="") as fh:
                    contents[hunk.path] = fh.read()
            except OSError as err:
                failures.append(f"FAIL hunk {hunk.index} {hunk.path}: {err.strerror}")
                continue
        try:
            contents[hunk.path], report = apply(hunk, contents[hunk.path])
            reports.append(report)
        except SpecError as err:
            failures.append(f"FAIL hunk {hunk.index} {hunk.path}: {err}")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        print("nothing written", file=sys.stderr)
        return 1
    if not args.dry_run:
        for path, text in contents.items():
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
    print("\n".join(reports) + (" (dry run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
