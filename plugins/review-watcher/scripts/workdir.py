"""Choose the directory a session tab opens in.

Order: a worktree of the repo's clone that has the PR's head branch checked out, else the clone
at {hub}/{name} (the name part of owner/name), else the hub itself. Every gh or git failure becomes a fallback plus a short
note; nothing here raises for an environment problem, so a lookup can never fail a dispatch.
"""

import os
import re
import subprocess

import config
import launcher
from gh_client import GhError
from repos import is_full_name

GIT_TIMEOUT_SECONDS = 20
NOTE_LIMIT = 200
DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
# Inherited from a git hook or alias, these override `-C` and point git at another repository.
GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                     "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_PREFIX")


def clear_git_location(environ):
    """Drop GIT_LOCATION_VARS so every child process (gh, scans, git, the tabs) uses its own repository."""
    for name in GIT_LOCATION_VARS:
        environ.pop(name, None)


def run_git(args, run=subprocess.run, environ=None):
    """Run git; returns (returncode, stdout, stderr). Never raises for a missing or hung git."""
    environ = os.environ if environ is None else environ
    env = {k: v for k, v in environ.items() if k not in GIT_LOCATION_VARS}
    try:
        proc = run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                   timeout=GIT_TIMEOUT_SECONDS, env=env)
    except (OSError, subprocess.TimeoutExpired) as err:
        return 1, "", str(err)
    return proc.returncode, proc.stdout, proc.stderr


def parse_worktrees(text):
    """Parse `git worktree list --porcelain -z` into [(path, branch or None, is_bare)].

    Fields are NUL-separated and a record ends with an empty field. A detached worktree has no
    branch. Bare records are returned so callers can count them.
    """
    records = []
    current = {}

    def flush():
        if "path" in current:
            records.append((current["path"], current.get("branch"), current.get("bare", False)))

    for field in text.split("\0"):
        if not field:
            flush()
            current = {}
        elif field.startswith("worktree "):
            current["path"] = field[len("worktree "):]
        elif field.startswith("branch "):
            current["branch"] = field[len("branch "):]
        elif field == "bare":
            current["bare"] = True
    flush()
    return records


def other_platform(path, os_name, environ):
    """True when git printed the path in the form the other platform uses (Windows git vs WSL git)."""
    if os_name == "nt":
        return path.startswith("/")
    return bool(environ.get("WSL_DISTRO_NAME")) and bool(DRIVE_PREFIX.match(path))


def short(text):
    return " ".join(str(text).split())[:NOTE_LIMIT]


def choose(hub, repo, pr, gh, git=run_git, isdir=os.path.isdir, exists=os.path.exists,
           fallback="clone", os_name=None, environ=None, safe_cwd=launcher.WIN_SAFE):
    """Return (cwd, problem) for `repo` in owner/name form. problem is None or a short reason a lookup failed."""
    os_name = os.name if os_name is None else os_name
    environ = os.environ if environ is None else environ
    if not is_full_name(repo):
        return hub, "unsafe repo name"
    main = os.path.join(hub, repo.split("/", 1)[1])
    has_git = exists(os.path.join(main, ".git"))
    if not isdir(main) or not (has_git or exists(os.path.join(main, ".bare"))):
        return hub, None
    state = {"bare": not has_git}

    def fall(problem=None):
        if state["bare"]:
            note = f"the clone at {main} is bare"
            return hub, f"{problem}; {note}" if problem else note
        return (hub if fallback == "root" else main), problem

    git_dir = main if has_git else os.path.join(main, ".bare")
    rc, out, err = git(["-C", git_dir, "worktree", "list", "--porcelain", "-z"])
    if rc != 0:
        return fall(f"git worktree list failed: {short(err or out)}")
    records = parse_worktrees(out)
    state["bare"] = bool(records) and records[0][2]
    if len(records) < 2 or gh is None:
        return fall()
    try:
        view = gh.json(["pr", "view", str(pr), "-R", repo, "--json",
                        "headRefName,isCrossRepository"])
    except (GhError, ValueError, OSError) as err:
        return fall(f"could not read the head branch: {short(err)}")
    head = view.get("headRefName") if isinstance(view, dict) else None
    if not isinstance(head, str) or not head:
        return fall("could not read the head branch: unexpected response")
    if view.get("isCrossRepository"):
        return fall()
    note = None
    # The first record is the main checkout: it is the fallback, never a match, so a PR branch
    # checked out there resolves the same whether or not other worktrees exist.
    for path, branch, is_bare in records[1:]:
        if is_bare or branch != f"refs/heads/{head}":
            continue
        if other_platform(path, os_name, environ):
            note = note or f"worktree {path} is not reachable from this platform"
            continue
        if not isdir(path):
            continue
        cwd = config.native_path(path)
        if not safe_cwd.match(cwd):
            note = note or f"worktree {path} has characters the launcher refuses"
            continue
        return cwd, None
    return fall(note)
