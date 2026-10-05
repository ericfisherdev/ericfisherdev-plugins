#!/usr/bin/env python3
"""Shared GitHub plumbing for the jira-sprint-workflow helper scripts.

The three callers (ci_failure.py, merge_readiness.py, job_history.py) all need the
same two things: run a `gh` command and get parsed JSON back, and work out which
OWNER/NAME repo the caller meant. Keeping that here means a fix to either applies
to all three.

Repo resolution deliberately understands the bare-clone-plus-worktrees layout these
repos use, because a caller naturally passes the directory it thinks of as "the
repo" (literec-admin-php/) rather than the worktree that actually holds a git
remote (literec-admin-php/main/).
"""

import json
import os
import shutil
import subprocess
import sys

TIMEOUT = 60


def die(message, code=2):
    """Exit with a one-line reason.

    Code 2 is reserved for "this tool could not answer", keeping 0 and 1 free for
    each script's own green/red verdict.
    """
    sys.exit(f"{message}" if code == 0 else f"error: {message}")


def gh(args, parse_json=True, allow_failure=False):
    """Run a gh command, returning parsed JSON (or raw text when parse_json is False)."""
    if not shutil.which("gh"):
        die("gh CLI not found on PATH")
    proc = subprocess.run(
        ["gh", *args], capture_output=True, text=True, timeout=TIMEOUT
    )
    if proc.returncode != 0:
        if allow_failure:
            return None
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        die(f"gh {' '.join(args[:3])} failed: {detail[0] if detail else 'no output'}")
    if not parse_json:
        return proc.stdout
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError:
        die(f"gh {' '.join(args[:3])} returned non-JSON output")


def gh_api(path, method=None, fields=None, allow_failure=False):
    """Call the REST API. allow_failure turns a 404 into None rather than an exit."""
    args = ["api", path]
    if method:
        args += ["--method", method]
    for key, value in (fields or {}).items():
        args += ["-f", f"{key}={value}"]
    return gh(args, allow_failure=allow_failure)


def graphql(query, variables):
    """Call the GraphQL API. Integer variables go through -F so they stay integers."""
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        flag = "-F" if isinstance(value, int) else "-f"
        args += [flag, f"{key}={value}"]
    return gh(args)


def resolve_slug(slug=None, repo_path=None):
    """Return OWNER/NAME.

    Order: an explicit --slug wins; then the git remote of --repo (trying the
    bare-clone `main/` worktree when the path itself has no remote); then whatever
    repo the current directory belongs to.
    """
    if slug:
        return slug
    for candidate in _remote_candidates(repo_path):
        url = _git_remote(candidate)
        if url:
            return _slug_from_url(url)
    detected = gh(
        ["repo", "view", "--json", "nameWithOwner"], allow_failure=True
    )
    if detected and detected.get("nameWithOwner"):
        return detected["nameWithOwner"]
    die("could not determine the repo; pass --slug OWNER/NAME or --repo PATH")


def _remote_candidates(repo_path):
    if not repo_path:
        return [os.getcwd()]
    root = os.path.abspath(os.path.expanduser(repo_path))
    return [root, os.path.join(root, "main")]


def _git_remote(path):
    if not os.path.isdir(path):
        return None
    proc = subprocess.run(
        ["git", "-C", path, "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def _slug_from_url(url):
    cleaned = url.strip()
    if cleaned.endswith(".git"):
        cleaned = cleaned[: -len(".git")]
    if cleaned.startswith("git@"):
        cleaned = cleaned.split(":", 1)[-1]
    else:
        cleaned = "/".join(cleaned.split("/")[-2:])
    return cleaned


def add_repo_args(parser):
    """Every script takes the same two ways of naming a repo."""
    parser.add_argument("--slug", help="OWNER/NAME; skips repo detection")
    parser.add_argument(
        "--repo", help="path to the repo (bare-clone layouts may point at the parent)"
    )
