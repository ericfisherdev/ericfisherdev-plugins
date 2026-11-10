#!/usr/bin/env python3
"""Turn the verifier's output into the numbered, anchored finding list the user chooses from.

    findings.py finalize owner/name N

Reads `verified.json` (and `refuted.json` when the refuter ran) from the PR's run directory,
checks their shape, applies the refuter's verdicts, enforces the shared definition of blocking,
decides which findings can be inline comments, proposes the review event, records the pass in
the ledger as pending, writes `findings.json`, and prints the list as markdown.

When a blocking finding has not been through the refuter yet it prints
`{"status": "refute", "prompt": ...}` instead and changes nothing.
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ledger import Dirs, Disposition, Ledger, LedgerError, state_root  # noqa: E402

RULES = Path(__file__).resolve().parent.parent / "rules"


class Severity(Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    NIT = "nit"

    @property
    def rank(self) -> int:
        return list(Severity).index(self)


class Category(Enum):
    CORRECTNESS = "correctness"
    SECURITY = "security"
    DATA_INTEGRITY = "data-integrity"
    ERROR_HANDLING = "error-handling"
    PERFORMANCE = "performance"
    COMPATIBILITY = "compatibility"
    DEPLOY = "deploy"
    TEST_COVERAGE = "test-coverage"
    MAINTAINABILITY = "maintainability"
    DOCS = "docs"
    STYLE = "style"


class Event(Enum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    COMMENT = "COMMENT"


class Anchor(Enum):
    INLINE = "inline"
    BODY = "body"


class RefuterVerdict(Enum):
    STANDS = "stands"
    DOWNGRADED = "downgraded"
    REFUTED = "refuted"


# A finding in one of these categories describes no runtime consequence, so it never blocks a merge.
NEVER_BLOCKING = frozenset({Category.TEST_COVERAGE, Category.MAINTAINABILITY, Category.DOCS, Category.STYLE})
BLOCKING_SEVERITIES = frozenset({Severity.CRITICAL, Severity.MAJOR})


class FindingsError(Exception):
    """The verifier's or refuter's file is missing, unreadable, or not in the agreed shape."""


@dataclass
class Finding:
    key: str
    file: str
    line: int
    severity: Severity
    blocking: bool
    category: Category
    title: str
    body: str
    start_line: Optional[int] = None
    suggestion: Optional[str] = None
    sources: List[str] = field(default_factory=list)
    checked: str = ""
    anchor: Anchor = Anchor.BODY
    number: int = 0

    @property
    def ledger_key(self) -> str:
        return f"{self.file}:{self.key}"

    def to_json(self) -> dict:
        data = asdict(self)
        data.update(severity=self.severity.value, category=self.category.value, anchor=self.anchor.value)
        return data

    @classmethod
    def from_json(cls, data: dict) -> "Finding":
        """Raises FindingsError naming the first field that is missing or has the wrong type or value."""
        try:
            finding = cls(
                key=str(data["key"]), file=str(data["file"]), line=int(data["line"]),
                severity=Severity(data["severity"]), blocking=bool(data["blocking"]),
                category=Category(data["category"]), title=str(data["title"]).strip(), body=str(data["body"]).strip(),
                start_line=int(data["start_line"]) if data.get("start_line") is not None else None,
                suggestion=data.get("suggestion") or None, sources=list(data.get("sources") or []),
                checked=str(data.get("checked") or ""), anchor=Anchor(data.get("anchor", Anchor.BODY.value)),
                number=int(data.get("number", 0)))
        except (KeyError, TypeError, ValueError) as exc:
            raise FindingsError(f"finding {data.get('key') or data.get('title') or '?'}: bad field ({exc})") from None
        if not finding.key or not finding.title or not finding.body:
            raise FindingsError(f"finding at {finding.file}:{finding.line} needs a key, a title and a body")
        return finding


def read_json(path: Path) -> dict:
    """Raises FindingsError when the file is missing or is not a JSON object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FindingsError(f"cannot read {path}: {exc}") from None
    if not isinstance(data, dict):
        raise FindingsError(f"{path} must hold a JSON object")
    return data


def load_verified(path: Path) -> Tuple[List[Finding], List[dict], str]:
    data = read_json(path)
    raw = data.get("findings")
    if not isinstance(raw, list):
        raise FindingsError(f"{path} needs a 'findings' array")
    findings = [Finding.from_json(item) for item in raw]
    keys = [f.ledger_key for f in findings]
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    if duplicated:
        raise FindingsError(f"duplicate finding keys: {', '.join(duplicated)}")
    return findings, list(data.get("dropped") or []), str(data.get("summary") or "").strip()


def enforce_blocking(finding: Finding) -> None:
    """Blocking needs a runtime consequence: a blocking-capable severity in a category that can have one."""
    if finding.category in NEVER_BLOCKING or finding.severity not in BLOCKING_SEVERITIES:
        finding.blocking = False
    if finding.severity is Severity.CRITICAL and finding.category not in NEVER_BLOCKING:
        finding.blocking = True


def apply_refuter(findings: List[Finding], dropped: List[dict], verdicts: List[dict]) -> List[Finding]:
    """Raises FindingsError when a verdict names an unknown finding or carries an unknown value."""
    by_key = {f.ledger_key: f for f in findings}
    for item in verdicts:
        try:
            finding = by_key[f"{item['file']}:{item['key']}"]
            verdict = RefuterVerdict(item["verdict"])
            reason = str(item["reason"])
            if verdict is RefuterVerdict.DOWNGRADED:
                finding.severity = Severity(item["severity"])
                finding.blocking = bool(item["blocking"])
        except (KeyError, TypeError, ValueError) as exc:
            raise FindingsError(f"refuter verdict for {item.get('key', '?')}: bad field ({exc})") from None
        if verdict is RefuterVerdict.REFUTED:
            findings = [f for f in findings if f is not finding]
            dropped.append({"title": finding.title, "file": finding.file, "line": finding.line, "key": finding.key,
                            "reason": reason, "disposition": Disposition.REFUTED.value})
    return findings


def place(finding: Finding, anchors: Dict[str, List[List[int]]]) -> None:
    """Inline when the diff shows the line; a start line survives only inside the same hunk."""
    finding.anchor = Anchor.BODY
    for start, end in anchors.get(finding.file, []):
        if start <= finding.line <= end:
            finding.anchor = Anchor.INLINE
            if finding.start_line is not None and not start <= finding.start_line < finding.line:
                finding.start_line = None
            return
    finding.start_line = None


def propose_event(findings: List[Finding], own_pr: bool, draft: bool, unreviewed: bool = False) -> Event:
    """An approval never covers files nobody read, so skipped files cap a clean review at COMMENT."""
    if own_pr or draft:
        return Event.COMMENT
    if any(f.blocking for f in findings):
        return Event.REQUEST_CHANGES
    return Event.COMMENT if unreviewed else Event.APPROVE


def number(findings: List[Finding]) -> List[Finding]:
    ordered = sorted(findings, key=lambda f: (not f.blocking, f.severity.rank, f.file, f.line))
    for index, finding in enumerate(ordered, start=1):
        finding.number = index
    return ordered


def label(finding: Finding) -> str:
    return finding.severity.value.capitalize() + (", blocking" if finding.blocking else "")


def render(plan: dict, findings: List[Finding], dropped: List[dict], summary: str, event: Event) -> str:
    lines = [f"## {plan['repo']}#{plan['pr']}: {plan['title']}", "",
             f"Reviewed `{plan['head'][:9]}` ({plan['mode']}, {plan['band']}, {plan['lines']} lines). "
             f"Proposed review: **{event.value}**.", ""]
    if summary:
        lines += [summary, ""]
    if not findings:
        lines += ["No findings survived verification.", ""]
    for finding in findings:
        where = f"{finding.file}:{finding.line}" + ("" if finding.anchor is Anchor.INLINE else " (review body)")
        lines += [f"**{finding.number}. [{label(finding)}] {finding.title}**",
                  f"`{where}` · {finding.category.value} · raised by {', '.join(finding.sources) or 'unknown'}", "",
                  finding.body, ""]
        if finding.suggestion:
            lines += ["```suggestion", finding.suggestion.rstrip("\n"), "```", ""]
    if dropped:
        lines += [f"Dropped {len(dropped)} candidate(s) during verification:"]
        lines += [f"- {item.get('title', '?')} ({item.get('file', '?')}:{item.get('line', '?')}): "
                  f"{item.get('reason', 'no reason given')}" for item in dropped]
        lines.append("")
    if plan.get("unreviewed"):
        lines += [f"Not reviewed ({len(plan['unreviewed'])} lockfile, generated, vendored or binary file(s)), so this "
                  "review cannot approve: " + ", ".join(f"`{path}`" for path in plan["unreviewed"]), ""]
    if plan.get("review_decision"):
        lines.append(f"Current review state on GitHub: {plan['review_decision']}.")
    lines += [f"Note: {note}" for note in plan.get("notes", [])]
    return "\n".join(lines).rstrip() + "\n"


def refuter_prompt(run: Path, tree: Optional[str]) -> str:
    return (f"Review pack: {run}. Read {run / 'manifest.md'} first. "
            f"Findings to attack: every entry with \"blocking\": true in {run / 'verified.json'}. "
            f"Tree at the PR head: {tree or 'none, work from the diff at ' + str(run / 'review.patch')}. "
            f"Shared rules: {RULES / 'severity.md'}, {RULES / 'scope.md'}. "
            f"Write your verdicts to {run / 'refuted.json'} and reply with only the count of each verdict.")


def record_pass(ledger: Ledger, plan: dict, findings: List[Finding], dropped: List[dict], event: Event, now: str) -> None:
    sha = plan["head"]
    ledger.open_pass({"sha": sha, "at": now, "mode": plan["mode"], "band": plan["band"],
                      "kept": len(findings), "dropped": len(dropped), "proposed": event.value})
    for finding in findings:
        ledger.record(finding.ledger_key, sha, Disposition.PENDING, "awaiting the reviewer's selection",
                      title=finding.title, file=finding.file, line=finding.line,
                      severity=finding.severity.value, blocking=finding.blocking)
    for item in dropped:
        key = f"{item.get('file', '?')}:{item.get('key') or item.get('title', '?')}"
        try:
            disposition = Disposition(item.get("disposition", Disposition.DROPPED.value))
        except ValueError:
            disposition = Disposition.DROPPED
        ledger.record(key, sha, disposition, str(item.get("reason") or "no reason given"),
                      title=item.get("title"), file=item.get("file"), line=item.get("line"))
    ledger.save()


def finalize(repo: str, pr: int, *, root: Path, now: str) -> dict:
    """Raises FindingsError on a malformed verifier or refuter file, LedgerError on a corrupt ledger."""
    dirs = Dirs(root, repo, pr)
    plan = read_json(dirs.run / "plan.json")
    findings, dropped, summary = load_verified(dirs.run / "verified.json")
    for finding in findings:
        enforce_blocking(finding)
    refuted_path = dirs.run / "refuted.json"
    if any(f.blocking for f in findings):
        if not refuted_path.exists():
            return {"status": "refute", "agent": "pr-reviewer:refuter", "prompt": refuter_prompt(dirs.run, plan.get("tree"))}
        findings = apply_refuter(findings, dropped, list(read_json(refuted_path).get("verdicts") or []))
        for finding in findings:
            enforce_blocking(finding)
    anchors = read_json(dirs.run / "anchors.json")
    for finding in findings:
        place(finding, anchors)
    findings = number(findings)
    event = propose_event(findings, plan.get("own_pr", False), plan.get("draft", False), bool(plan.get("unreviewed")))
    record_pass(Ledger.load(dirs.ledger), plan, findings, dropped, event, now)
    (dirs.run / "findings.json").write_text(json.dumps(
        {"summary": summary, "proposed_event": event.value, "findings": [f.to_json() for f in findings],
         "dropped": dropped}, indent=2) + "\n", encoding="utf-8")
    return {"status": "ready", "total": len(findings), "blocking": sum(f.blocking for f in findings),
            "proposed_event": event.value, "markdown": render(plan, findings, dropped, summary, event)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    cmd = sub.add_parser("finalize")
    cmd.add_argument("repo")
    cmd.add_argument("pr", type=int)
    args = parser.parse_args(argv)
    try:
        result = finalize(args.repo, args.pr, root=state_root(), now=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    except (FindingsError, LedgerError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 1
    markdown = result.pop("markdown", None)
    print(json.dumps(result))
    if markdown:
        print()
        print(markdown, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
