#!/usr/bin/env python3
"""Find repetitive tool calls in Claude Code session transcripts and rank them by token cost.

    scriptify.py                      last 2 weeks, every project
    scriptify.py --period 1w          last week; units: h (hours), d (days), w (weeks)
    scriptify.py --project obsidiboard   only project directories whose name contains the text
    scriptify.py --format json        machine-readable output
    scriptify.py --top 15 --examples 3

Reads `~/.claude/projects/**/*.jsonl` (or `$CLAUDE_CONFIG_DIR/projects`), pairs every
tool_use with its tool_result, drops copies of the same tool_use id (a project directory
that was renamed keeps a copy of its transcripts; a command run three times in one
session counts three times), and buckets Bash commands by task shape.
Token counts are characters / 4 for the command text (input) and the result (output).

Savings are estimates: measured tokens multiplied by a per-category factor listed in
the report, chosen from how much of such a call is boilerplate or overshoot that a
purpose-built script removes. Treat them as a ranking, not a budget.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field

CHARS_PER_TOKEN = 4
PERIOD_UNITS = {"h": 3600, "d": 86400, "w": 7 * 86400}
BASH_TOOLS = {"Bash", "bash"}
CD_PREFIX = re.compile(r"^\s*(?:(?:cd\s+(?:\"[^\"]*\"|'[^']*'|\S+)|set -e|set -euo pipefail|[A-Za-z_][\w]*=(?:\"[^\"]*\"|'[^']*'|\S+))\s*(?:&&|;)\s*)+")
STRING_LITERAL = re.compile(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'')


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    pattern: re.Pattern[str]
    savings_factor: float
    rationale: str
    covered_by: str = ""


# Order matters: the first matching category wins.
CATEGORIES: list[Category] = [
    Category("inline_python_edit", "Inline python string-replace edits",
             re.compile(r"python3?\s+(?:-I\s+)?-\s*<<[\s\S]{0,400}?(?:\.replace\(|def (?:sub|patch|edit)\()"),
             0.35, "helper boilerplate plus assert tracebacks that echo the old text", "patch.py"),
    Category("dts_lookup", "Type declaration lookups in .d.ts files",
             re.compile(r"\.d\.ts\b"), 0.5, "sed ranges overshoot the declaration; grep-then-sed is two calls", "dts_lookup.py"),
    Category("multi_file_dump", "Whole-directory cat loops",
             re.compile(r"\bfor \w+ in [^;]*;\s*do\s+(?:echo[^;]*;\s*)?cat(?: -n)?\s"), 0.75, "an outline replaces a full dump for orientation", "src_outline.py"),
    Category("pr_status_review", "PR status, checks, review threads",
             re.compile(r"gh pr (?:view|checks|list)|gh run list|gh api (?:graphql|repos/\S+/pulls/)|pulls/\d+/(?:comments|reviews)"),
             0.6, "long --json/--jq selectors in, verbose JSON out", "pr.py"),
    Category("pr_lifecycle", "PR create, merge, ready, run logs",
             re.compile(r"gh pr (?:create|merge|ready)|gh run view"), 0.3, "fixed flag sets per repo; a wrapper removes retyping"),
    Category("gh_repo_research", "GitHub repository research (readme, releases, contents)",
             re.compile(r"gh api (?:repos/\S+/(?:readme|releases|contents|license)|\"?search/code)|api\.github\.com/repos"),
             0.6, "base64 readme dumps and release JSON compress to a few lines"),
    Category("hf_model_research", "Hugging Face model research",
             re.compile(r"huggingface\.co/(?:api/models|[^/\s]+/[^/\s]+/resolve)"), 0.6, "model card and config JSON compress to a summary line"),
    Category("npm_registry", "npm registry version checks",
             re.compile(r"\bnpm (?:view|info|pack)\b|registry\.npmjs\.org"), 0.5, "per-package JSON compresses to name@version date"),
    Category("http_fetch", "Raw HTTP fetches (curl/wget)",
             re.compile(r"^\s*(?:curl|wget)\b"), 0.4, "page bodies are rarely needed whole"),
    Category("ssh_remote", "Remote shell over ssh/scp/rsync",
             re.compile(r"^\s*(?:ssh|scp|rsync)\b"), 0.2, "mostly ad hoc; only repeated host checks script well"),
    Category("git_sync_worktree", "Fetch, status, worktree setup",
             re.compile(r"git (?:fetch|worktree|status -sb)"), 0.5, "fixed sequence per branch", ),
    Category("git_history", "Git log, show, diff, blame",
             re.compile(r"^\s*git (?:log|show|diff|blame)\b"), 0.2, "output size depends on the question"),
    Category("claude_plugin_cli", "claude plugin validate/test",
             re.compile(r"\bclaude plugin \w+"), 0.5, "only failures matter; pass lines are noise"),
    Category("test_build", "Test and build runs",
             re.compile(r"^\s*(?:npm (?:run|test)|npx (?:vitest|jest|tsc|eslint)|cargo (?:test|build|check|clippy)|pytest|go (?:test|build|vet)|make\b|composer|phpunit)"),
             0.4, "a failures-only wrapper drops passing output"),
    Category("file_read", "File reads via sed/cat/head/tail",
             re.compile(r"^\s*(?:sed -n|cat\b(?! >)|head\b|tail\b|wc\b|cat -n)"), 0.15, "blank-line stripping and outlines trim orientation reads", "src_outline.py"),
    Category("search", "grep/rg/find searches",
             re.compile(r"^\s*(?:grep|rg|find|fd)\b"), 0.1, "mostly irreducible; tighten patterns instead"),
    Category("write_file", "File writes via heredoc",
             re.compile(r"\bcat\s*>>?\s*\S+\s*<<"), 0.0, "content is the payload; nothing to script"),
    Category("inline_python_other", "Other inline python",
             re.compile(r"python3?\s+(?:-I\s+)?(?:-c\b|-\s*<<)"), 0.25, "repeated analysis snippets become a script with flags"),
]


@dataclass
class Call:
    project: str
    session: str
    tool: str
    tool_input: dict
    result_chars: int
    timestamp: float
    use_id: str = ""


@dataclass
class Bucket:
    key: str
    label: str
    savings_factor: float
    rationale: str
    covered_by: str
    calls: int = 0
    in_chars: int = 0
    out_chars: int = 0
    sessions: set[str] = field(default_factory=set)
    projects: set[str] = field(default_factory=set)
    examples: dict[str, int] = field(default_factory=dict)

    def add(self, call: Call, command: str) -> None:
        self.calls += 1
        self.in_chars += len(command)
        self.out_chars += call.result_chars
        self.sessions.add(call.session)
        self.projects.add(call.project)
        shape = " ".join(command.split())[:160]
        self.examples[shape] = self.examples.get(shape, 0) + 1

    @property
    def in_tokens(self) -> int:
        return self.in_chars // CHARS_PER_TOKEN

    @property
    def out_tokens(self) -> int:
        return self.out_chars // CHARS_PER_TOKEN

    @property
    def total_tokens(self) -> int:
        return self.in_tokens + self.out_tokens

    @property
    def estimated_savings(self) -> int:
        return int(self.total_tokens * self.savings_factor)


def parse_period(spec: str) -> float:
    match = re.fullmatch(r"(\d+)([hdw])", spec.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError(f"period must look like 2w, 3d or 12h, got {spec!r}")
    return int(match.group(1)) * PERIOD_UNITS[match.group(2)]


def projects_dir() -> str:
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return os.path.join(config, "projects")


def parse_timestamp(value: object) -> float:
    if not isinstance(value, str):
        return 0.0
    try:
        from datetime import datetime
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def result_chars(block: dict) -> int:
    content = block.get("content")
    if isinstance(content, list):
        return sum(len(part.get("text", "")) for part in content if isinstance(part, dict))
    return len(str(content or ""))


def load_calls(root: str, cutoff: float, project_filter: str | None) -> tuple[list[Call], int]:
    calls: list[Call] = []
    pending: dict[str, tuple[Call, None]] = {}
    files = 0
    for path in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        if os.path.getmtime(path) < cutoff:
            continue
        project = os.path.relpath(path, root).split(os.sep)[0]
        if project_filter and project_filter not in project:
            continue
        files += 1
        session = os.path.basename(path)
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = entry.get("message")
                if not isinstance(message, dict) or not isinstance(message.get("content"), list):
                    continue
                stamp = parse_timestamp(entry.get("timestamp"))
                for block in message["content"]:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        call = Call(project, session, block.get("name", "?"), block.get("input") or {}, 0, stamp,
                                    block.get("id", ""))
                        pending[block.get("id", "")] = (call, None)
                    elif block.get("type") == "tool_result" and block.get("tool_use_id") in pending:
                        call, _ = pending.pop(block["tool_use_id"])
                        call.result_chars = result_chars(block)
                        if call.timestamp == 0.0 or call.timestamp >= cutoff:
                            calls.append(call)
    return dedupe(calls), files


def dedupe(calls: list[Call]) -> list[Call]:
    """Drop copies of a transcript. The tool_use id is unique per call and survives a copy,
    so it separates a copied transcript from the same command run again in one session."""
    seen: set[tuple] = set()
    unique: list[Call] = []
    for call in calls:
        if call.use_id:
            key = (call.session, call.use_id)
        else:
            key = (call.session, call.tool, json.dumps(call.tool_input, sort_keys=True)[:500],
                   call.result_chars, call.timestamp)
        if key in seen:
            continue
        seen.add(key)
        unique.append(call)
    return unique


def strip_prefix(command: str) -> str:
    return CD_PREFIX.sub("", command.strip())


def fallback_key(command: str) -> tuple[str, str]:
    tokens = command.split()
    if not tokens:
        return "empty", "Empty command"
    program = os.path.basename(tokens[0])
    if program in ("sudo", "env", "timeout", "nohup") and len(tokens) > 1:
        program = os.path.basename(tokens[1])
        tokens = tokens[1:]
    sub = tokens[1] if len(tokens) > 1 and not tokens[1].startswith("-") and "/" not in tokens[1] and "=" not in tokens[1] else ""
    key = f"{program} {sub}".strip()
    return "other:" + key, f"Other: {key}"


def categorize(command: str) -> Category | tuple[str, str]:
    stripped = strip_prefix(command)
    for category in CATEGORIES:
        if category.pattern.search(stripped):
            return category
    return fallback_key(stripped)


def bucket_bash(calls: list[Call]) -> list[Bucket]:
    buckets: dict[str, Bucket] = {}
    for call in calls:
        if call.tool not in BASH_TOOLS:
            continue
        command = call.tool_input.get("command", "")
        found = categorize(command)
        if isinstance(found, Category):
            bucket = buckets.setdefault(found.key, Bucket(found.key, found.label, found.savings_factor, found.rationale, found.covered_by))
        else:
            key, label = found
            bucket = buckets.setdefault(key, Bucket(key, label, 0.3, "repeated shape; a script with flags removes retyping", ""))
        bucket.add(call, command)
    return sorted(buckets.values(), key=lambda b: -b.estimated_savings)


def python_edit_boilerplate(calls: list[Call]) -> tuple[int, int]:
    """Tokens of python edit heredocs that are not string payload, and traceback output tokens."""
    boilerplate = tracebacks = 0
    pattern = CATEGORIES[0].pattern
    for call in calls:
        if call.tool not in BASH_TOOLS:
            continue
        command = strip_prefix(call.tool_input.get("command", ""))
        if not pattern.search(command):
            continue
        payload = sum(len(s) for s in STRING_LITERAL.findall(command))
        boilerplate += len(command) - payload
        if call.result_chars > 150:
            tracebacks += call.result_chars
    return boilerplate // CHARS_PER_TOKEN, tracebacks // CHARS_PER_TOKEN


def verbatim_repeats(calls: list[Call], minimum: int) -> list[tuple[str, int, int]]:
    counter: collections.Counter[str] = collections.Counter()
    out_chars: collections.Counter[str] = collections.Counter()
    for call in calls:
        if call.tool not in BASH_TOOLS:
            continue
        shape = " ".join(call.tool_input.get("command", "").split())
        if shape:
            counter[shape] += 1
            out_chars[shape] += call.result_chars
    return [(cmd, n, out_chars[cmd] // CHARS_PER_TOKEN) for cmd, n in counter.most_common() if n >= minimum]


def read_rereads(calls: list[Call]) -> tuple[int, int, list[tuple[str, int]]]:
    per_session: collections.Counter[tuple[str, str]] = collections.Counter()
    size: dict[tuple[str, str], int] = {}
    for call in calls:
        if call.tool != "Read":
            continue
        key = (call.session, call.tool_input.get("file_path", ""))
        per_session[key] += 1
        size[key] = call.result_chars
    wasted_calls = sum(n - 1 for n in per_session.values() if n > 1)
    wasted_tokens = sum((n - 1) * size[k] for k, n in per_session.items() if n > 1) // CHARS_PER_TOKEN
    by_file: collections.Counter[str] = collections.Counter()
    for (_, path), n in per_session.items():
        if n > 1:
            by_file[path] += n - 1
    return wasted_calls, wasted_tokens, by_file.most_common(5)


def tool_totals(calls: list[Call]) -> list[tuple[str, int, int, int]]:
    counts: collections.Counter[str] = collections.Counter()
    in_chars: collections.Counter[str] = collections.Counter()
    out_chars: collections.Counter[str] = collections.Counter()
    for call in calls:
        counts[call.tool] += 1
        in_chars[call.tool] += len(json.dumps(call.tool_input))
        out_chars[call.tool] += call.result_chars
    return [(t, n, in_chars[t] // CHARS_PER_TOKEN, out_chars[t] // CHARS_PER_TOKEN) for t, n in counts.most_common(12)]


def short_project_names(all_projects: set[str]) -> dict[str, str]:
    """Strip the shared prefix (usually the home directory) from project directory names."""
    names = sorted(all_projects)
    prefix = os.path.commonprefix(names) if len(names) > 1 else ""
    prefix = prefix[: prefix.rfind("-") + 1]
    return {name: name[len(prefix):] or name for name in names}


def render_markdown(args: argparse.Namespace, calls: list[Call], files: int, buckets: list[Bucket]) -> str:
    lines: list[str] = []
    sessions = {c.session for c in calls}
    projects = {c.project for c in calls}
    short = short_project_names(projects)
    lines.append(f"# Scriptify report: last {args.period}")
    lines.append("")
    lines.append(f"Transcripts: {files} files, {len(sessions)} sessions, {len(projects)} projects, {len(calls)} tool calls after dedupe.")
    lines.append("")
    lines.append("## Tool totals (tokens ~ chars/4)")
    lines.append("")
    lines.append("| tool | calls | in | out |")
    lines.append("|---|---|---|---|")
    for tool, n, i, o in tool_totals(calls):
        lines.append(f"| {tool} | {n} | {i} | {o} |")
    lines.append("")
    lines.append("## Bash task shapes ranked by estimated savings")
    lines.append("")
    lines.append("| # | task shape | calls | sessions | in | out | measured | factor | est. save | covered by |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    shown = [b for b in buckets if b.calls >= args.min_calls][: args.top]
    for rank, b in enumerate(shown, 1):
        lines.append(f"| {rank} | {b.label} | {b.calls} | {len(b.sessions)} | {b.in_tokens} | {b.out_tokens} | {b.total_tokens} | {b.savings_factor:.2f} | {b.estimated_savings} | {b.covered_by or '-'} |")
    lines.append("")
    lines.append("Factor = share of measured tokens a purpose-built script is expected to remove; rationale per shape below.")
    lines.append("")
    boilerplate, tracebacks = python_edit_boilerplate(calls)
    if boilerplate or tracebacks:
        lines.append(f"Inline python edits: {boilerplate} tokens of non-payload boilerplate, {tracebacks} tokens of traceback output (measured, not estimated).")
        lines.append("")
    for rank, b in enumerate(shown, 1):
        lines.append(f"### {rank}. {b.label}")
        lines.append("")
        lines.append(f"- why scriptable: {b.rationale}")
        lines.append(f"- projects: {', '.join(sorted(short[p] for p in b.projects))}")
        if b.covered_by:
            lines.append(f"- already covered by opticlaude `{b.covered_by}` (run /opticlaude:setup if the calls still appear)")
        lines.append("- examples:")
        for shape, n in sorted(b.examples.items(), key=lambda kv: (-kv[1], len(kv[0])))[: args.examples]:
            lines.append(f"  - ({n}x) `{shape}`")
        lines.append("")
    repeats = verbatim_repeats(calls, args.min_repeats)
    lines.append(f"## Verbatim repeated commands (>= {args.min_repeats}x)")
    lines.append("")
    if repeats:
        for cmd, n, out in repeats[:15]:
            lines.append(f"- {n}x, {out} out tokens: `{cmd[:140]}`")
    else:
        lines.append("none")
    lines.append("")
    wasted_calls, wasted_tokens, by_file = read_rereads(calls)
    lines.append("## Read tool: same file re-read within one session")
    lines.append("")
    lines.append(f"{wasted_calls} re-reads, about {wasted_tokens} tokens. Not scriptable; a note in CLAUDE.md to read once and work from line numbers helps.")
    for path, n in by_file:
        lines.append(f"- {n}x {path}")
    lines.append("")
    return "\n".join(lines)


def render_json(args: argparse.Namespace, calls: list[Call], files: int, buckets: list[Bucket]) -> str:
    wasted_calls, wasted_tokens, by_file = read_rereads(calls)
    payload = {
        "period": args.period,
        "files": files,
        "sessions": len({c.session for c in calls}),
        "calls": len(calls),
        "tools": [dict(zip(("tool", "calls", "in_tokens", "out_tokens"), row)) for row in tool_totals(calls)],
        "shapes": [
            {
                "key": b.key, "label": b.label, "calls": b.calls, "sessions": len(b.sessions), "projects": sorted(b.projects),
                "in_tokens": b.in_tokens, "out_tokens": b.out_tokens, "measured_tokens": b.total_tokens,
                "savings_factor": b.savings_factor, "estimated_savings": b.estimated_savings, "rationale": b.rationale,
                "covered_by": b.covered_by,
                "examples": [{"command": s, "count": n} for s, n in sorted(b.examples.items(), key=lambda kv: -kv[1])[: args.examples]],
            }
            for b in buckets if b.calls >= args.min_calls
        ][: args.top],
        "verbatim_repeats": [{"command": c, "count": n, "out_tokens": o} for c, n, o in verbatim_repeats(calls, args.min_repeats)[:15]],
        "read_rereads": {"calls": wasted_calls, "tokens": wasted_tokens, "files": [{"path": p, "count": n} for p, n in by_file]},
    }
    return json.dumps(payload, indent=1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--period", default="2w", help="look-back window such as 2w, 3d, 12h (default 2w)")
    ap.add_argument("--project", help="only project directories whose name contains this text")
    ap.add_argument("--projects-dir", default=projects_dir(), help="transcript root (default: ~/.claude/projects)")
    ap.add_argument("--format", choices=("md", "json"), default="md")
    ap.add_argument("--top", type=int, default=12, help="task shapes to list")
    ap.add_argument("--examples", type=int, default=3, help="example commands per shape")
    ap.add_argument("--min-calls", type=int, default=3, help="hide shapes with fewer calls")
    ap.add_argument("--min-repeats", type=int, default=3, help="threshold for verbatim repeats")
    args = ap.parse_args()

    try:
        window = parse_period(args.period)
    except argparse.ArgumentTypeError as err:
        ap.error(str(err))
    if not os.path.isdir(args.projects_dir):
        print(f"no transcript directory at {args.projects_dir}", file=sys.stderr)
        return 2
    calls, files = load_calls(args.projects_dir, time.time() - window, args.project)
    if not calls:
        print("no tool calls in the selected window", file=sys.stderr)
        return 1
    buckets = bucket_bash(calls)
    print(render_json(args, calls, files, buckets) if args.format == "json" else render_markdown(args, calls, files, buckets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
