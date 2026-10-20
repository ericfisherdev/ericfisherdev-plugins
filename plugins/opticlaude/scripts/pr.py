#!/usr/bin/env python3
"""Compact GitHub pull-request status and review-thread handling via `gh`.

    pr.py status  [-R owner/repo] [N ...]        one line per PR (all open PRs when no N)
    pr.py checks  [-R owner/repo] N              every check with status, failures first
    pr.py threads [-R owner/repo] N [--all]      review threads (unresolved by default)
    pr.py resolve [-R owner/repo] THREAD_ID ...  resolve review threads
    pr.py reply   [-R owner/repo] N COMMENT_ID BODY   reply to a review comment (BODY `-` reads stdin)

Status line: `#N STATE [draft] review=DECISION merge=STATUS ci=ok/fail/pending head=sha branch unresolved=K | title`.
Thread line: `THREAD_ID path:line @author c=COMMENT_ID: body` where COMMENT_ID is what `reply` takes.
Repo defaults to the checkout in the current directory. Exit 1 when gh fails.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

PR_FIELDS = """
  number title state isDraft reviewDecision mergeable mergeStateStatus
  headRefName headRefOid baseRefName url
  commits(last: 1) { nodes { commit { statusCheckRollup { state contexts(first: 100) { nodes {
    __typename
    ... on CheckRun { name status conclusion detailsUrl }
    ... on StatusContext { context state targetUrl }
  } } } } } }
  reviewThreads(first: 100) { nodes { isResolved isOutdated } }
"""
THREAD_FIELDS = """
  reviewThreads(first: 100) { nodes {
    id isResolved isOutdated path line
    comments(first: 1) { nodes { databaseId author { login } body url } }
  } }
"""


def gh(*args: str, stdin: str | None = None) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, input=stdin)
    if result.returncode != 0:
        sys.stderr.write(result.stderr.strip() + "\n")
        sys.exit(1)
    return result.stdout


def graphql(query: str, **variables: str | int) -> dict:
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        args += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    return json.loads(gh(*args))["data"]


def default_repo() -> str:
    return gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner").strip()


def split_repo(repo: str) -> tuple[str, str]:
    owner, _, name = repo.partition("/")
    if not name:
        sys.exit(f"repo must be owner/name, got {repo!r}")
    return owner, name


def fetch_prs(repo: str, numbers: list[int]) -> list[dict]:
    owner, name = split_repo(repo)
    if numbers:
        parts = " ".join(f"pr{n}: pullRequest(number: {n}) {{ {PR_FIELDS} }}" for n in numbers)
        data = graphql(f"query {{ repository(owner: \"{owner}\", name: \"{name}\") {{ {parts} }} }}")
        return [data["repository"][f"pr{n}"] for n in numbers]
    data = graphql(
        f"query {{ repository(owner: \"{owner}\", name: \"{name}\") {{ pullRequests(states: OPEN, first: 50, orderBy: {{field: UPDATED_AT, direction: DESC}}) {{ nodes {{ {PR_FIELDS} }} }} }} }}"
    )
    return data["repository"]["pullRequests"]["nodes"]


def check_contexts(pr: dict) -> list[dict]:
    commits = pr["commits"]["nodes"]
    rollup = commits[0]["commit"]["statusCheckRollup"] if commits else None
    return rollup["contexts"]["nodes"] if rollup else []


def check_outcome(ctx: dict) -> str:
    if ctx["__typename"] == "CheckRun":
        if ctx["status"] != "COMPLETED":
            return "pending"
        return "ok" if ctx["conclusion"] in ("SUCCESS", "NEUTRAL", "SKIPPED") else "fail"
    state = ctx["state"]
    return "ok" if state == "SUCCESS" else "pending" if state in ("PENDING", "EXPECTED") else "fail"


def status_line(pr: dict) -> str:
    outcomes = [check_outcome(c) for c in check_contexts(pr)]
    ci = f"{outcomes.count('ok')}ok/{outcomes.count('fail')}fail/{outcomes.count('pending')}pending" if outcomes else "none"
    unresolved = sum(1 for t in pr["reviewThreads"]["nodes"] if not t["isResolved"])
    draft = " draft" if pr["isDraft"] else ""
    return (
        f"#{pr['number']} {pr['state']}{draft} review={pr['reviewDecision'] or 'NONE'} merge={pr['mergeStateStatus']} "
        f"ci={ci} head={pr['headRefOid'][:7]} {pr['headRefName']}->{pr['baseRefName']} unresolved={unresolved} | {pr['title']}"
    )


def cmd_status(args: argparse.Namespace) -> None:
    prs = fetch_prs(args.repo, args.numbers)
    if not prs:
        print("no open pull requests")
    for pr in prs:
        print(status_line(pr))


def cmd_checks(args: argparse.Namespace) -> None:
    pr = fetch_prs(args.repo, [args.number])[0]
    rows = []
    for ctx in check_contexts(pr):
        name = ctx.get("name") or ctx.get("context")
        url = ctx.get("detailsUrl") or ctx.get("targetUrl") or ""
        rows.append((check_outcome(ctx), name, url))
    if not rows:
        print("no checks")
    order = {"fail": 0, "pending": 1, "ok": 2}
    for outcome, name, url in sorted(rows, key=lambda r: order[r[0]]):
        print(f"{outcome:7} {name}" + (f"  {url}" if outcome != "ok" else ""))


def cmd_threads(args: argparse.Namespace) -> None:
    owner, name = split_repo(args.repo)
    data = graphql(
        f"query($n: Int!) {{ repository(owner: \"{owner}\", name: \"{name}\") {{ pullRequest(number: $n) {{ {THREAD_FIELDS} }} }} }}",
        n=args.number,
    )
    threads = data["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    shown = 0
    for thread in threads:
        if thread["isResolved"] and not args.all:
            continue
        comment = thread["comments"]["nodes"][0]
        body = " ".join(comment["body"].split())
        if len(body) > args.width:
            body = body[: args.width - 1] + "…"
        flags = ("resolved " if thread["isResolved"] else "") + ("outdated " if thread["isOutdated"] else "")
        location = f"{thread['path']}:{thread['line']}" if thread["line"] else thread["path"]
        print(f"{thread['id']} {location} @{comment['author']['login']} c={comment['databaseId']} {flags}: {body}")
        shown += 1
    if shown == 0:
        print("no unresolved threads" if not args.all else "no threads")


def cmd_resolve(args: argparse.Namespace) -> None:
    for thread_id in args.thread_ids:
        data = graphql(f"mutation {{ resolveReviewThread(input: {{threadId: \"{thread_id}\"}}) {{ thread {{ id isResolved }} }} }}")
        thread = data["resolveReviewThread"]["thread"]
        print(f"{'resolved' if thread['isResolved'] else 'NOT resolved'} {thread['id']}")


def cmd_reply(args: argparse.Namespace) -> None:
    body = sys.stdin.read() if args.body == "-" else args.body
    out = gh("api", "--method", "POST", f"repos/{args.repo}/pulls/{args.number}/comments/{args.comment_id}/replies", "-f", f"body={body}")
    reply = json.loads(out)
    print(f"replied id={reply['id']} {reply['html_url']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-R", "--repo", help="owner/name (default: current checkout)")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status"); p.add_argument("numbers", nargs="*", type=int); p.set_defaults(run=cmd_status)
    p = sub.add_parser("checks"); p.add_argument("number", type=int); p.set_defaults(run=cmd_checks)
    p = sub.add_parser("threads"); p.add_argument("number", type=int); p.add_argument("--all", action="store_true")
    p.add_argument("--width", type=int, default=200, help="max body chars per thread"); p.set_defaults(run=cmd_threads)
    p = sub.add_parser("resolve"); p.add_argument("thread_ids", nargs="+"); p.set_defaults(run=cmd_resolve)
    p = sub.add_parser("reply"); p.add_argument("number", type=int); p.add_argument("comment_id"); p.add_argument("body"); p.set_defaults(run=cmd_reply)

    args = ap.parse_args()
    args.repo = args.repo or default_repo()
    args.run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
