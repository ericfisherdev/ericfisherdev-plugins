"""Thin wrappers around the gh and git CLIs. Standard library only.

Both take an injectable runner so the unit tests never touch GitHub or a real repository.
"""

import json
import re
import subprocess
from typing import List, Optional

TIMEOUT_SECONDS = 120
PR_FIELDS = ("number,title,body,author,state,isDraft,baseRefName,headRefName,headRefOid,"
             "additions,deletions,changedFiles,url,reviewDecision")
THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        nodes { isResolved isOutdated path line
                comments(first: 20) { nodes { author { login } body } } }
      }
    }
  }
}"""


class CommandError(Exception):
    """A gh or git command failed, timed out, or is not installed."""


class CommandTimeout(CommandError):
    """The command did not finish in time, so whether it took effect is unknown."""


def run_command(argv: List[str], cwd: Optional[str] = None, run=subprocess.run):
    try:
        proc = run(argv, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise CommandTimeout(f"{' '.join(argv[:3])} timed out after {TIMEOUT_SECONDS}s") from None
    except FileNotFoundError:
        raise CommandError(f"{argv[0]} is not installed or not on PATH") from None
    return proc.returncode, proc.stdout, proc.stderr


class Gh:
    def __init__(self, runner=run_command):
        self._runner = runner

    def _run(self, args: List[str]) -> str:
        """stdout of `gh args`. Raises CommandError on any failure."""
        rc, out, err = self._runner(["gh", *args])
        if rc != 0:
            raise CommandError(f"gh {' '.join(args[:3])} failed: {(err or '').strip()[:500]}")
        return out

    def pr_view(self, repo: str, pr: int) -> dict:
        """Raises CommandError when the PR or the repository cannot be read."""
        return json.loads(self._run(["pr", "view", str(pr), "-R", repo, "--json", PR_FIELDS]))

    def pr_head(self, repo: str, pr: int) -> str:
        return self._run(["pr", "view", str(pr), "-R", repo, "--json", "headRefOid", "-q", ".headRefOid"]).strip()

    def pr_diff(self, repo: str, pr: int) -> str:
        return self._run(["pr", "diff", str(pr), "-R", repo])

    def viewer(self) -> str:
        return self._run(["api", "user", "--jq", ".login"]).strip()

    def review_threads(self, repo: str, pr: int) -> List[dict]:
        owner, name = repo.split("/", 1)
        out = self._run(["api", "graphql", "-f", f"query={THREADS_QUERY}", "-F", f"owner={owner}",
                         "-F", f"name={name}", "-F", f"number={pr}"])
        payload = json.loads(out)
        pull = ((payload.get("data") or {}).get("repository") or {}).get("pullRequest") or {}
        return (pull.get("reviewThreads") or {}).get("nodes") or []

    def post_review(self, repo: str, pr: int, payload_path: str) -> str:
        """The posted review's URL. Raises CommandError when GitHub refuses the payload."""
        return self._run(["api", f"repos/{repo}/pulls/{pr}/reviews", "--method", "POST",
                          "--input", payload_path, "--jq", ".html_url"]).strip()


class Git:
    def __init__(self, runner=run_command):
        self._runner = runner

    def _try(self, cwd: str, args: List[str]):
        rc, out, err = self._runner(["git", *args], cwd=cwd)
        return rc, out, err

    def _run(self, cwd: str, args: List[str]) -> str:
        rc, out, err = self._try(cwd, args)
        if rc != 0:
            raise CommandError(f"git {' '.join(args[:3])} failed: {(err or '').strip()[:500]}")
        return out

    def toplevel(self, cwd: str) -> Optional[str]:
        rc, out, _ = self._try(cwd, ["rev-parse", "--show-toplevel"])
        if rc != 0:
            return None
        return out.strip() or None

    def origin_matches(self, cwd: str, repo: str) -> bool:
        rc, out, _ = self._try(cwd, ["remote", "get-url", "origin"])
        if rc != 0:
            return False
        slug = re.sub(r"\.git$", "", out.strip().replace(":", "/"))
        return slug.lower().endswith("/" + repo.lower())

    def head(self, cwd: str) -> str:
        return self._run(cwd, ["rev-parse", "HEAD"]).strip()

    def is_clean(self, cwd: str) -> bool:
        return not self._run(cwd, ["status", "--porcelain", "--untracked-files=no"]).strip()

    def has_commit(self, cwd: str, sha: str) -> bool:
        rc, _, _ = self._try(cwd, ["cat-file", "-e", f"{sha}^{{commit}}"])
        return rc == 0

    def is_ancestor(self, cwd: str, old: str, new: str) -> bool:
        rc, _, _ = self._try(cwd, ["merge-base", "--is-ancestor", old, new])
        return rc == 0

    def fetch_pr(self, cwd: str, pr: int) -> None:
        self._run(cwd, ["fetch", "--quiet", "origin", f"pull/{pr}/head"])

    def add_worktree(self, cwd: str, path: str, sha: str) -> None:
        self._run(cwd, ["worktree", "add", "--detach", "--quiet", path, sha])

    def remove_worktree(self, cwd: str, path: str) -> None:
        self._run(cwd, ["worktree", "remove", "--force", path])

    def diff_range(self, cwd: str, old: str, new: str) -> str:
        return self._run(cwd, ["diff", f"{old}..{new}"])
