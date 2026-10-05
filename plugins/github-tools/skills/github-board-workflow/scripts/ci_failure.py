#!/usr/bin/env python3
"""Why is CI red? Answers in a few lines instead of a log dump.

Reading a failure by hand is four steps every time: list runs, find the failing
one, list its jobs to find the failing job and step, then page through
`gh run view --log-failed` hunting the one line that matters. This collapses that
into a single command whose output is small enough for an orchestrator to hold.

Usage:
  ci_failure.py --pr N            [--repo PATH | --slug OWNER/NAME] [--lines N]
  ci_failure.py --branch NAME     [--repo PATH | --slug OWNER/NAME] [--lines N]
  ci_failure.py --run RUN_ID      [--repo PATH | --slug OWNER/NAME] [--lines N]

Exit status: 0 when everything is green, 1 when at least one job failed, 2 when
the question could not be answered. That makes it usable as a gate:
  ci_failure.py --pr 217 || echo "do not merge"

Only failing jobs are reported. Passing jobs are counted, never listed — a list of
things that worked is exactly the payload this is meant to avoid.
"""

import argparse
import re
import sys

import gh_common as gh

# Lines worth surfacing from a failing step's log. Ordered by how decisive they
# are: a PHPUnit assertion message tells you more than a generic "Error:".
DECISIVE_PATTERNS = [
    r"Failed asserting that",
    r"^\d+\) \S+::\S+",            # PHPUnit's numbered failure header
    r"FAILURES!|ERRORS!|OK, but",  # PHPUnit's summary line
    r"\bAssertionError\b|\bTypeError\b|\bValueError\b",
    r"^\s*Error:|^\s*Fatal error:|Uncaught \w+Exception",
    r"npm ERR!",
    r"^\s*✘|^not ok ",             # Playwright / TAP
    r"\.php:\d+$|\.ts:\d+:\d+|\.py\", line \d+",
    r"Finding:|RuleID:|leaks? found",     # gitleaks / secret scanning
]
DECISIVE = re.compile("|".join(DECISIVE_PATTERNS))

# Used only when nothing better matched. Every failing step emits this, so it would
# drown out the real message if it competed with the patterns above.
FALLBACK = re.compile(r"Process completed with exit code \d+|##\[error\]")

# gh prefixes every log line with "job\tstep\ttimestamp ". Strip that so the caller sees
# the message, not the bookkeeping.
LOG_PREFIX = re.compile(r"^.*?\d{4}-\d{2}-\d{2}T[\d:.]+Z\s")

# Runner logs carry ANSI colour, and gh renders the escape byte as a literal "^["
# pair in some logs, so both forms have to go or the line arrives unreadable.
ANSI = re.compile(r"(?:\x1b|\^\[)\[[0-9;]*[A-Za-z]")

MAX_LOG_BYTES = 2_000_000


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--pr", type=int, help="pull request number")
    target.add_argument("--branch", help="branch name")
    target.add_argument("--run", type=int, help="a specific workflow run id")
    parser.add_argument(
        "--lines", type=int, default=4, help="decisive log lines per failing job (default 4)"
    )
    gh.add_repo_args(parser)
    args = parser.parse_args()

    slug = gh.resolve_slug(args.slug, args.repo)
    runs = _runs_for_target(slug, args)
    if not runs:
        print("no workflow runs found for that target")
        return 2

    failures = []
    passed = 0
    for run in runs:
        for job in _jobs(slug, run["databaseId"]):
            if job.get("conclusion") == "success":
                passed += 1
            elif job.get("conclusion") not in (None, "skipped", "neutral"):
                failures.append((run, job))

    for run, job in failures:
        _report(slug, run, job, args.lines)

    print()
    if failures:
        print(f"VERDICT: {len(failures)} job(s) failing, {passed} passing")
        return 1
    print(f"VERDICT: all green ({passed} jobs)")
    return 0


def _runs_for_target(slug, args):
    """Resolve the target to the newest run per workflow, so one command covers
    a repo whose checks are split across several workflow files."""
    if args.run:
        return [{"databaseId": args.run, "name": f"run {args.run}"}]

    branch = args.branch
    if args.pr:
        pr = gh.gh(
            ["pr", "view", str(args.pr), "-R", slug, "--json", "headRefName,headRefOid"]
        )
        branch = pr["headRefName"]

    listed = gh.gh(
        [
            "run", "list", "-R", slug, "--branch", branch, "--limit", "30",
            "--json", "databaseId,name,conclusion,status,headSha,createdAt",
        ]
    )
    newest_sha = listed[0]["headSha"] if listed else None
    # Only the current head matters. An older red run on a superseded commit is
    # noise, and treating it as live is how "green" gets misread.
    return _newest_per_workflow(r for r in listed if r["headSha"] == newest_sha)


def _newest_per_workflow(runs):
    seen = {}
    for run in runs:
        seen.setdefault(run["name"], run)
    return list(seen.values())


def _jobs(slug, run_id):
    data = gh.gh(["run", "view", str(run_id), "-R", slug, "--json", "jobs"], allow_failure=True)
    return (data or {}).get("jobs", [])


def _report(slug, run, job, max_lines):
    steps = [
        s["name"]
        for s in job.get("steps", [])
        if s.get("conclusion") not in ("success", "skipped", None)
    ]
    print(f"FAILED  {job['name']}  [{run.get('name', '?')}]")
    for step in steps:
        print(f"  step: {step}")
    for line in _decisive_lines(slug, run["databaseId"], job["name"], max_lines):
        print(f"  | {line}")
    if job.get("url"):
        print(f"  {job['url']}")


def _decisive_lines(slug, run_id, job_name, max_lines):
    """Pull the failing log and keep only lines that explain the failure.

    The log is fetched once per run and filtered in memory; --log-failed on a big
    suite is megabytes, which is the whole reason this script exists.
    """
    raw = gh.gh(
        ["run", "view", str(run_id), "-R", slug, "--log-failed"],
        parse_json=False,
        allow_failure=True,
    )
    if not raw:
        return ["(log unavailable — the run may still be in progress)"]

    hits, fallback = [], []
    for line in raw[:MAX_LOG_BYTES].splitlines():
        if job_name not in line:
            continue
        # Clean first, then match: several patterns anchor with ^, which never
        # fires while gh's job/step/timestamp prefix is still attached.
        cleaned = ANSI.sub("", LOG_PREFIX.sub("", line)).strip()
        if not cleaned:
            continue
        if not DECISIVE.search(cleaned):
            if FALLBACK.search(cleaned) and cleaned not in fallback:
                fallback.append(cleaned)
            continue
        if cleaned not in hits:
            hits.append(cleaned)
        if len(hits) >= max_lines:
            break
    return (
        hits
        or fallback[:max_lines]
        or ["(no recognisable failure line — open the job URL)"]
    )


if __name__ == "__main__":
    sys.exit(main())
