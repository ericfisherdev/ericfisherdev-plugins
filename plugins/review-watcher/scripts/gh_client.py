"""Thin wrapper around the gh CLI shared by the review-watcher scripts.

Standard library only. All GitHub access goes through `gh`, so authentication is whatever
`gh auth login` set up. The runner is injectable so the unit tests can use a fake.
"""

import json
import os
import re
import subprocess
import sys

RATE_LIMIT_PATTERN = re.compile(r"rate limit|HTTP 429|secondary rate", re.IGNORECASE)
# Upper bound for one gh call (a paginated call counts as one). A stalled gh must not hang a poll tick.
GH_TIMEOUT_SECONDS = 120


class GhError(Exception):
    pass


class RateLimited(GhError):
    pass


class StateError(Exception):
    """The watcher state file exists but cannot be read or parsed."""


def subprocess_runner(args, input=None, run=subprocess.run):
    try:
        proc = run(["gh", *args], input=input, capture_output=True, text=True, timeout=GH_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise GhError(f"gh {' '.join(args[:3])} timed out after {GH_TIMEOUT_SECONDS}s")
    except FileNotFoundError:
        raise GhError("the GitHub CLI (gh) is not installed or not on PATH; install it from "
                      "https://cli.github.com and run 'gh auth login'") from None
    return proc.returncode, proc.stdout, proc.stderr


class GhClient:
    def __init__(self, runner=subprocess_runner):
        self.runner = runner

    def run(self, args, input=None):
        """stdout of `gh args`. Raises RateLimited on a rate limit, GhError on any other failure."""
        rc, out, err = self.runner(args, input=input)
        if rc != 0:
            if RATE_LIMIT_PATTERN.search(err or ""):
                raise RateLimited(err.strip())
            raise GhError(f"gh {' '.join(args[:3])} failed: {(err or '').strip()[:500]}")
        return out

    def json(self, args, input=None):
        out = self.run(args, input=input)
        return json.loads(out) if out.strip() else None

    def rest_list(self, path):
        """GET every page of a REST list endpoint.

        `gh api --paginate` prints one JSON array per page, which is not valid JSON as a whole;
        `--jq '.[]'` flattens that into one compact JSON object per line.
        """
        out = self.run(["api", path, "--paginate", "--jq", ".[]"])
        return [json.loads(line) for line in out.splitlines() if line.strip()]

    def current_login(self):
        return self.run(["api", "user", "--jq", ".login"]).strip()

    def canonical_repo(self, full_name):
        """The repository's owner/name as GitHub spells it. Raises GhError when it is missing or hidden."""
        return self.run(["repo", "view", full_name, "--json", "nameWithOwner", "--jq", ".nameWithOwner"]).strip()


def load_state(path):
    """Read a watcher state file; a missing file is an empty state.

    A file that exists but cannot be read, is not valid JSON, or is not a JSON object raises
    StateError naming the path, so a half-written file is a one-line fix instead of a silent stall.
    """
    full = os.path.expanduser(path)
    try:
        with open(full, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as err:
        raise StateError(f"cannot read state file at {full}: {err}")
    try:
        data = json.loads(text)
    except ValueError as err:
        raise StateError(f"state file at {full} is not valid JSON ({err}); fix or delete it")
    if not isinstance(data, dict):
        raise StateError(f"state file at {full} must hold a JSON object; fix or delete it")
    return data


def emit(obj):
    json.dump(obj, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")


def main_guard(fn):
    """Run a CLI entry point; print {"error": ...} JSON and exit non-zero on gh failures."""
    try:
        fn()
    except RateLimited:
        emit({"error": "rate_limited"})
        sys.exit(2)
    except GhError as exc:
        emit({"error": "gh_failed", "detail": str(exc)})
        sys.exit(1)
    except StateError as exc:
        emit({"error": "bad_state", "detail": str(exc)})
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 - callers parse stdout as JSON, so never print a traceback
        emit({"error": "internal", "detail": f"{type(exc).__name__}: {exc}"[:500]})
        sys.exit(1)


def add_me_argument(parser):
    parser.add_argument("--me", help="GitHub login to act as (default: the gh login; pass it to save one API call)")


def resolve_me(client, args):
    return args.me or client.current_login()
