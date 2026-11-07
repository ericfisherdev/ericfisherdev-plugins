#!/usr/bin/env python3
"""Record the outcome of a review session in the watcher ledger.

The session the watcher opened runs this once when its workflow finishes. The watcher folds
the report into the ledger on its next tick, so a session that never reports stays in flight.

Usage:
  report.py [--ledger PATH] --repo OWNER/NAME --pr N [--session NAME] [--dispatch ID]
            --outcome posted|skipped|no-op|failed [--head SHA]

--ledger defaults to ledger.json in the plugin state dir, so clearing a stuck PR by hand needs
only --repo, --pr and --outcome. --dispatch is the id in the session's prompt; a report whose id
does not match the session in flight is refused. Prints one JSON object; exits 1 with {"error": ...}.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ledger  # noqa: E402
from config import state_dir  # noqa: E402
from events import OUTCOMES  # noqa: E402
from gh_client import StateError  # noqa: E402
from repos import is_full_name  # noqa: E402

HEAD_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")


class ReportError(Exception):
    pass


def record(path, repo, pr, outcome, session=None, head=None, now=None, dispatch=None):
    """Attach the report to the session in flight.

    Raises ReportError for a bad repo or sha, no session in flight, or a session or dispatch
    mismatch; StateError for an unreadable ledger; ledger.LedgerBusy when the lock stays taken.
    """
    if not is_full_name(repo):
        raise ReportError(f"invalid repo: {repo!r}; expected owner/name")
    if head is not None and not HEAD_PATTERN.match(head):
        raise ReportError(f"invalid head sha: {head!r}; expected 7 to 40 lowercase hex characters")
    key = f"{repo}#{pr}"
    now = now or datetime.now(timezone.utc)
    # A session reports once, so it must outwait a crashed writer's lock until that lock is breakable.
    with ledger.update(path, timeout=ledger.WRITER_LOCK_STALE_SECONDS + 15) as data:
        entry = data["active"].get(key)
        if entry is None:
            raise ReportError(f"no review session in flight for {key}")
        if session is not None and session != entry.get("session"):
            raise ReportError(f"session mismatch for {key}: in flight is {entry.get('session')!r}, got {session!r}")
        # Every session for a PR shares its name, so only the dispatch id tells a late report from an
        # earlier window apart from the session now in flight.
        if dispatch is not None and dispatch != entry.get("dispatch"):
            raise ReportError(f"dispatch mismatch for {key}: in flight is {entry.get('dispatch')!r}, got {dispatch!r}; "
                              "this report is from an earlier session")
        replaced = "report" in entry
        entry["report"] = {"outcome": outcome, "head_sha": head,
                           "finished_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    return {"ok": True, "key": key, "outcome": outcome, "replaced": replaced}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ledger", default=None)
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--session")
    parser.add_argument("--dispatch")
    parser.add_argument("--outcome", required=True, choices=tuple(OUTCOMES))
    parser.add_argument("--head")
    args = parser.parse_args(argv)
    path = args.ledger or str(state_dir() / "ledger.json")
    try:
        out = record(path, args.repo, args.pr, args.outcome, args.session, args.head, dispatch=args.dispatch)
    except (ReportError, StateError, ledger.LedgerBusy) as err:
        print(json.dumps({"error": str(err)}))
        return 1
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
