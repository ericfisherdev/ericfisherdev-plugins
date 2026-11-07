#!/usr/bin/env python3
"""Manage the watched repositories in <state dir>/repos.json.

The watcher reads this file at the start of every tick, so a change takes effect on the next
tick without restarting it. Each entry is a GitHub repository in owner/name form.

Usage:
  repos.py list
  repos.py add owner/name [owner/name ...]      (each one is checked with `gh repo view`)
  repos.py remove owner/name [owner/name ...]

Prints one JSON object: {"repos": [...]} plus "added"/"already"/"removed"/"missing" lists for
add and remove. Exits 1 with {"error": "..."} on a malformed name, a repository gh cannot see,
or an unreadable repos.json; nothing is written when any name in an add is refused.
"""

import argparse
import json
import re
import sys

import config
from gh_client import GhClient, GhError

# Owners: 1-39 letters, digits or hyphens, starting with a letter or digit. Names: letters, digits, . _ -.
FULL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
FILE_NAME = "repos.json"


class RepoError(Exception):
    pass


def is_full_name(value):
    """True for a well-formed owner/name that cannot climb out of a directory."""
    if not isinstance(value, str) or not FULL_NAME_PATTERN.match(value):
        return False
    return value.split("/", 1)[1] not in (".", "..")


def parse_full_name(value):
    """The stripped owner/name. Raises RepoError for anything else."""
    name = value.strip() if isinstance(value, str) else value
    if not is_full_name(name):
        raise RepoError(f"{value!r} is not a repository in owner/name form, for example octocat/hello-world")
    return name


def repos_path(env=None, home=None):
    return config.state_dir(env, home) / FILE_NAME


def read_repos(path):
    """The watched repositories, [] when the file is missing. Raises RepoError for a bad file."""
    try:
        data = config.read_json_object(path)
    except config.ConfigError as err:
        raise RepoError(str(err))
    repos = data.get("repos", [])
    if not isinstance(repos, list) or not all(is_full_name(r) for r in repos):
        raise RepoError(f"{path} must hold {{\"repos\": [\"owner/name\", ...]}}; fix or delete it")
    return repos


def write_repos(path, repos):
    config.write_json_atomic(path, {"repos": sorted(repos, key=str.lower)}, ".repos-")


def folded(name):
    """GitHub matches owner and repository names case-insensitively."""
    return name.lower()


def add(path, names, canonical):
    """Add each name, spelt as `canonical(name)` returns it. Raises RepoError and writes nothing on any refusal."""
    current = read_repos(path)
    known = {folded(r) for r in current}
    added, already = [], []
    for raw in names:
        name = parse_full_name(raw)
        try:
            spelt = canonical(name)
        except GhError as err:
            raise RepoError(f"gh cannot see {name}: {err}")
        # A renamed or transferred repository answers with its new owner/name, which is the one to watch.
        if not is_full_name(spelt):
            raise RepoError(f"gh answered {spelt!r} for {name}; expected an owner/name")
        name = spelt
        if folded(name) in known:
            already.append(name)
            continue
        known.add(folded(name))
        added.append(name)
    repos = current + added
    if added:
        write_repos(path, repos)
    return {"repos": sorted(repos, key=str.lower), "added": added, "already": already}


def remove(path, names):
    """Remove each name; a name that is not watched is reported in "missing", not refused."""
    current = read_repos(path)
    wanted = {folded(parse_full_name(raw)): raw.strip() for raw in names}
    kept = [r for r in current if folded(r) not in wanted]
    removed = [r for r in current if folded(r) in wanted]
    gone = {folded(r) for r in removed}
    missing = [raw for key, raw in wanted.items() if key not in gone]
    if removed:
        write_repos(path, kept)
    return {"repos": sorted(kept, key=str.lower), "removed": removed, "missing": missing}


def main(argv=None, gh_factory=GhClient):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    for name in ("add", "remove"):
        cmd = sub.add_parser(name)
        cmd.add_argument("names", nargs="+", metavar="owner/name")
    args = parser.parse_args(argv)
    path = repos_path()
    try:
        if args.action == "list":
            out = {"repos": sorted(read_repos(path), key=str.lower)}
        elif args.action == "add":
            out = add(path, args.names, gh_factory().canonical_repo)
        else:
            out = remove(path, args.names)
    except RepoError as err:
        print(json.dumps({"error": str(err)}))
        return 1
    print(json.dumps(dict(out, file=str(path))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
