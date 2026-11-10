"""The per-PR review ledger: what each pass found, posted, and deliberately did not post.

It lives in the state directory, outside every repository, so a re-review can scope itself to the
commits since the last finished pass and keep a dismissed finding dismissed.
"""

import json
import os
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


class Disposition(Enum):
    PENDING = "pending"        # found, the user has not decided yet
    POSTED = "posted"          # sent to GitHub
    DECLINED = "declined"      # the user saw it and chose not to post it
    DROPPED = "dropped"        # the verifier could not confirm it, or it duplicated existing feedback
    REFUTED = "refuted"        # the refuter disproved it


class LedgerError(Exception):
    """The ledger file exists but cannot be read or parsed. It is never overwritten in that state."""


def state_root() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(base) / "pr-reviewer"


def slug(repo: str) -> str:
    return repo.replace("/", "__")


class Dirs:
    """Where one PR's files live under the state directory."""

    def __init__(self, root: Path, repo: str, pr: int):
        self.root = Path(root)
        self.run = self.root / "runs" / slug(repo) / str(pr)
        self.tree = self.root / "trees" / f"{slug(repo)}-{pr}"
        self.ledger = self.root / "ledger" / slug(repo) / f"{pr}.json"


class Ledger:
    def __init__(self, path: Path, data: Optional[dict] = None):
        self.path = Path(path)
        self.data = data or {"passes": [], "findings": {}}

    @classmethod
    def load(cls, path: Path) -> "Ledger":
        """Raises LedgerError when the file exists but is not a ledger."""
        path = Path(path)
        if not path.exists():
            return cls(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LedgerError(f"cannot read the ledger at {path}: {exc}") from None
        if not isinstance(data, dict) or not isinstance(data.get("passes"), list) \
                or not isinstance(data.get("findings"), dict):
            raise LedgerError(f"the ledger at {path} does not have the expected shape")
        return cls(path, data)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    @property
    def passes(self) -> List[dict]:
        return self.data["passes"]

    @property
    def findings(self) -> Dict[str, dict]:
        return self.data["findings"]

    def last_closed_sha(self) -> Optional[str]:
        """Head sha of the most recent pass the user finished; an abandoned pass does not count."""
        for entry in reversed(self.passes):
            if entry.get("closed"):
                return entry["sha"]
        return None

    def open_pass(self, entry: dict) -> None:
        """Record a pass before the user decides. A pass for the same sha that never closed is replaced."""
        self.data["passes"] = [p for p in self.passes if p.get("closed") or p.get("sha") != entry["sha"]]
        self.passes.append(dict(entry, closed=False))

    def close_pass(self, sha: str, **fields) -> None:
        for entry in reversed(self.passes):
            if entry.get("sha") == sha and not entry.get("closed"):
                entry.update(fields, closed=True)
                return
        raise LedgerError(f"no open pass for {sha} in {self.path}")

    def record(self, key: str, sha: str, disposition: Disposition, reason: str, **fields) -> None:
        self.findings[key] = dict(fields, disposition=disposition.value, reason=reason, sha=sha)

    def set_disposition(self, key: str, disposition: Disposition, reason: str) -> None:
        self.findings[key].update(disposition=disposition.value, reason=reason)

    def summary_lines(self) -> List[str]:
        """One line per recorded finding, for the verifier's prior-feedback file."""
        return [f"- [{entry['disposition']}] {entry.get('file', '?')}:{entry.get('line', '?')} "
                f"{entry.get('title', key)} (reviewed at {entry['sha'][:9]}): {entry['reason']}"
                for key, entry in self.findings.items()]
