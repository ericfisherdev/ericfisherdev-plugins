#!/usr/bin/env python3
"""Is this CI job a flake, or is it really broken on my branch?

Answers by counting one named job's pass/fail record per branch. That comparison is
the cheapest way to test a "known flake" claim: a flake fails intermittently
everywhere, while a real regression fails every time on one branch and nowhere else.
Getting this wrong in either direction is expensive — merging over a genuine failure,
or blocking a sprint on a documented flake.

Usage:
  job_history.py "<job name>" [--limit N] [--branch NAME] [--repo PATH | --slug OWNER/NAME]

  job_history.py "Fixtures smoke test" --limit 40
  job_history.py "PHPUnit" --branch main

The job name is matched case-insensitively as a substring, so "fixtures" finds
"Fixtures smoke test". Exit status is 0 whenever the history could be read; this
reports, it does not gate.

Cost note: job results are per-run, so this makes one API call per run inspected.
--limit defaults to 30 runs for that reason.
"""

import argparse
import collections
import sys

import gh_common as gh


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("job", help="job name, or a substring of it")
    parser.add_argument(
        "--limit", type=int, default=30, help="how many recent runs to inspect (default 30)"
    )
    parser.add_argument("--branch", help="restrict to one branch")
    gh.add_repo_args(parser)
    args = parser.parse_args()

    slug = gh.resolve_slug(args.slug, args.repo)
    runs = _recent_runs(slug, args.limit, args.branch)
    if not runs:
        print("no workflow runs found")
        return 0

    history = _collect(slug, runs, args.job.lower())
    if not history:
        print(f"no job matching '{args.job}' in the last {len(runs)} runs")
        return 0

    _print_table(history, args.job)
    print()
    print(_verdict(history))
    return 0


def _recent_runs(slug, limit, branch):
    command = [
        "run", "list", "-R", slug, "--limit", str(limit),
        "--json", "databaseId,headBranch,createdAt,status",
    ]
    if branch:
        command += ["--branch", branch]
    return [r for r in gh.gh(command) if r.get("status") == "completed"]


def _collect(slug, runs, needle):
    """Per-branch outcomes for every job whose name contains the needle.

    Each branch keeps its outcomes with timestamps, not just tallies: a mixed
    record means something completely different depending on whether the passes
    and failures interleave (a flake) or the failures all land after the passes
    (a regression that arrived at a known moment).
    """
    history = collections.defaultdict(list)
    for run in runs:
        data = gh.gh(
            ["run", "view", str(run["databaseId"]), "-R", slug, "--json", "jobs"],
            allow_failure=True,
        )
        for job in (data or {}).get("jobs", []):
            if needle not in job["name"].lower():
                continue
            outcome = job.get("conclusion")
            if outcome in (None, "skipped", "cancelled", "neutral"):
                continue
            history[run["headBranch"]].append(
                {"at": run.get("createdAt", ""), "ok": outcome == "success"}
            )
    return {branch: _summarise(events) for branch, events in history.items()}


def _summarise(events):
    """Collapse one branch's events into the shape the table and verdict need."""
    ordered = sorted(events, key=lambda e: e["at"])
    passes = [e for e in ordered if e["ok"]]
    fails = [e for e in ordered if not e["ok"]]
    regressed_at = None
    if passes and fails and fails[0]["at"] > passes[-1]["at"]:
        # Every failure is newer than every pass: not intermittent, it broke and
        # stayed broken. The first failure timestamp is the moment to investigate.
        regressed_at = fails[0]["at"]
    return {
        "pass": len(passes),
        "fail": len(fails),
        "latest": "success" if ordered and ordered[-1]["ok"] else "failure",
        "regressed_at": regressed_at,
    }


def _print_table(history, job_name):
    print(f"job: {job_name}")
    print(f"{'BRANCH':<45} {'PASS':>5} {'FAIL':>5}  LATEST")
    for branch, tally in sorted(
        history.items(), key=lambda kv: (-kv[1]["fail"], kv[0])
    ):
        note = ""
        if tally["regressed_at"]:
            note = f"  (broke at {tally['regressed_at'][:16].replace('T', ' ')})"
        print(
            f"{branch[:45]:<45} {tally['pass']:>5} {tally['fail']:>5}  "
            f"{tally['latest'] or '-'}{note}"
        )


def _verdict(history):
    """Turn the tallies into the judgement the caller actually wants.

    The interesting shape is a branch that fails every time while others never do:
    that is a real regression wearing a flake's clothes. A branch that both passes
    and fails is the genuine flake signature.
    """
    all_red = [b for b, t in history.items() if t["fail"] and not t["pass"]]
    regressed = [b for b, t in history.items() if t["regressed_at"]]
    flaky = [
        b for b, t in history.items()
        if t["fail"] and t["pass"] and not t["regressed_at"]
    ]
    clean = [b for b, t in history.items() if t["pass"] and not t["fail"]]

    if not all_red and not flaky and not regressed:
        return f"VERDICT: no failures across {len(clean)} branch(es) — job looks healthy"

    # Order matters: a branch that broke and stayed broken is the strongest signal,
    # and reading it as a flake is the expensive mistake this script exists to stop.
    if regressed:
        branch = sorted(regressed)[0]
        when = history[branch]["regressed_at"][:16].replace("T", " ")
        return (
            f"VERDICT: regression on {branch} — every failure is newer than every "
            f"pass, first red at {when}. Not a flake; find what landed then"
        )
    if all_red and clean:
        worst = max(all_red, key=lambda b: history[b]["fail"])
        count = history[worst]["fail"]
        return (
            f"VERDICT: deterministic on {worst} ({count}/{count} fail) while "
            f"{len(clean)} other branch(es) are clean — treat as a real failure, "
            f"not a flake"
        )
    if flaky:
        branches = ", ".join(sorted(flaky)[:3])
        return (
            f"VERDICT: intermittent on {branches} — passes and fails interleave on "
            f"the same branch, consistent with a flake"
        )
    worst = max(all_red, key=lambda b: history[b]["fail"])
    count = history[worst]["fail"]
    return (
        f"VERDICT: failing everywhere it ran ({worst}: {count}/{count}) — "
        f"likely broken on the base branch"
    )


if __name__ == "__main__":
    sys.exit(main())
