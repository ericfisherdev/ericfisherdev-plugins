#!/usr/bin/env python3
"""One review-watcher scan: find open PRs in the watched repos that request my review.

Reads the `seen` map from the watcher's ledger but never writes it. Prints one JSON object.

Usage:
  review_poll_scan.py --state LEDGER --repo owner/name [--repo owner/name ...] [--me <login>]
                      [--stale-days 10] [--limit 100]
"""

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gh_client import GhClient, GhError, add_me_argument, emit, load_state, main_guard, resolve_me  # noqa: E402
from repos import is_full_name  # noqa: E402

# Repositories per `gh search prs` call; keeps each search query well inside GitHub's length limit.
REPOS_PER_SEARCH = 20


def parse_ts(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def chunks(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


def search_requests(client, repos, me, limit):
    """Open PRs in `repos` that request my review, and whether any search hit `limit`."""
    results, truncated = [], False
    for group in chunks(repos, REPOS_PER_SEARCH):
        args = ["search", "prs"]
        for repo in group:
            args += ["--repo", repo]
        args += ["--state", "open", "--review-requested", me,
                 "--json", "repository,number,title,author,url", "--limit", str(limit)]
        page = client.json(args) or []
        truncated = truncated or len(page) >= limit
        results += page
    return results, truncated


def latest_request(client, repo, number, me):
    events = client.rest_list(f"repos/{repo}/issues/{number}/timeline")
    mine = [e for e in events
            if e.get("event") == "review_requested"
            and (e.get("requested_reviewer") or {}).get("login") == me]
    if not mine:
        return "unknown", ""
    last = mine[-1]
    return (last.get("actor") or {}).get("login") or "unknown", last.get("created_at") or ""


def latest_human_reply(client, repo, number, me):
    """Newest non-bot reply by someone else on a review thread that I started."""
    comments = client.rest_list(f"repos/{repo}/pulls/{number}/comments")
    my_roots = {c["id"] for c in comments
                if c.get("in_reply_to_id") is None and (c.get("user") or {}).get("login") == me}
    replies = [c["created_at"] for c in comments
               if c.get("in_reply_to_id") in my_roots
               and (c.get("user") or {}).get("login") != me
               and (c.get("user") or {}).get("type") != "Bot"]
    return max(replies) if replies else ""


def scan(client, me, seen, repos, stale_days=10, now=None, limit=100):
    """Raises GhError for a repository name that is not owner/name, and for any gh failure."""
    bad = [r for r in repos if not is_full_name(r)]
    if bad:
        raise GhError(f"invalid repository name: {bad[0]!r}")
    now = now or datetime.now(timezone.utc)
    results, truncated = search_requests(client, repos, me, limit)

    out = {
        "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pending_total": len(results),
        "pending_keys": [],
        "stale_ignored": 0,
        "already_handled": 0,
        "actionable": 0,
        "truncated": truncated,
        "new": [],
    }
    for pr in results:
        repo = pr["repository"]["nameWithOwner"]
        number = pr["number"]
        key = f"{repo}#{number}"
        out["pending_keys"].append(key)

        requester, requested_at = latest_request(client, repo, number, me)
        last_reply_at = latest_human_reply(client, repo, number, me)
        activity_at = max(requested_at, last_reply_at)

        if activity_at and (now - parse_ts(activity_at)).total_seconds() > stale_days * 86400:
            out["stale_ignored"] += 1
            continue

        stored = seen.get(key)
        # Newer activity on a PR whose review is still in flight also goes into `new`: the
        # watcher records it in `seen` and dispatches the follow-up review afterwards.
        if stored is not None and not activity_at > stored:
            out["already_handled"] += 1
            continue
        out["new"].append({
            "repo": repo,
            "pr": number,
            "title": pr.get("title", ""),
            "author": (pr.get("author") or {}).get("login", ""),
            "requester": requester,
            "requested_at": requested_at,
            "url": pr.get("url", ""),
            "last_reply_at": last_reply_at,
            "activity_at": activity_at,
            "trigger": "reply" if last_reply_at and last_reply_at > requested_at else "requested",
        })
    out["actionable"] = len(out["new"])
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", required=True, help="Path to the watcher's ledger.json")
    parser.add_argument("--repo", action="append", required=True, dest="repos", metavar="owner/name")
    parser.add_argument("--stale-days", type=int, default=10)
    parser.add_argument("--limit", type=int, default=100)
    add_me_argument(parser)
    args = parser.parse_args()

    state = load_state(args.state)
    client = GhClient()
    me = resolve_me(client, args)
    emit(scan(client, me, state.get("seen") or {}, args.repos, stale_days=args.stale_days, limit=args.limit))


if __name__ == "__main__":
    main_guard(main)
