#!/usr/bin/env python3
"""Close the tab a review session runs in, once that session's report is in the ledger.

A session runs this as its last action when closeTabWhenDone is set. A session that has not
reported keeps its tab, so a review that stopped early stays open for a look.

Usage:
  close_tab.py [--ledger PATH] --repo OWNER/NAME --pr N --dispatch ID

Only the tmux launcher can close its tabs: tmux sets TMUX_PANE for every process in a pane, and
killing that pane closes the session's window. On success the pane, and this process with it, is
gone; if it survives it prints {"ok": true, "pane": ...}. Exits 1 with {"error": ...} otherwise.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ledger  # noqa: E402
from config import state_dir  # noqa: E402
from gh_client import StateError  # noqa: E402

PANE_ID = re.compile(r"^%\d+$")
RUN_TIMEOUT_SECONDS = 30


class CloseError(Exception):
    pass


def require_report(data, repo, pr, dispatch):
    """Raises CloseError unless the session `dispatch` for repo#pr has reported.

    The watcher may already have moved the entry from active to done, so both are checked.
    """
    key = f"{repo}#{pr}"
    for section in ("active", "done"):
        entry = data[section].get(key)
        if entry and entry.get("dispatch") == dispatch:
            if "report" not in entry:
                raise CloseError(f"{key} has not reported yet; run report.py first")
            return
    raise CloseError(f"no session {dispatch} for {key} in the ledger; this tab is not the one in flight")


def own_pane(env):
    """The tmux pane this process runs in. Raises CloseError outside tmux."""
    pane = env.get("TMUX_PANE", "")
    if not PANE_ID.match(pane):
        raise CloseError("not running inside a tmux pane; only the tmux launcher can close its tabs")
    return pane


def kill_pane(pane, which=shutil.which, runner=subprocess.run):
    """Raises CloseError when tmux is missing or refuses."""
    tmux = which("tmux")
    if not tmux:
        raise CloseError("tmux was not found on PATH")
    try:
        result = runner([tmux, "kill-pane", "-t", pane], capture_output=True, text=True,
                        timeout=RUN_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise CloseError(f"tmux could not be run: {err}") from err
    if result.returncode != 0:
        raise CloseError(f"tmux kill-pane failed: {(result.stderr or '').strip() or f'exit {result.returncode}'}")


def close(path, repo, pr, dispatch, env=None, which=shutil.which, runner=subprocess.run):
    """Close the calling session's tab after checking it reported.

    Raises CloseError for a missing report, a dispatch mismatch, no tmux pane or a tmux failure;
    StateError for an unreadable ledger.
    """
    env = os.environ if env is None else env
    pane = own_pane(env)
    with ledger.snapshot(path) as data:
        require_report(data, repo, pr, dispatch)
    kill_pane(pane, which, runner)
    return {"ok": True, "pane": pane}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ledger", default=None)
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--dispatch", required=True)
    args = parser.parse_args(argv)
    path = args.ledger or str(state_dir() / "ledger.json")
    try:
        out = close(path, args.repo, args.pr, args.dispatch)
    except (CloseError, StateError) as err:
        print(json.dumps({"error": str(err)}))
        return 1
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
