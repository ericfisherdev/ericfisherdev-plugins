#!/usr/bin/env python3
"""Post the findings the user selected as one GitHub review and close the pass in the ledger.

    post.py owner/name N --select all|none|1,3,5 [--approve] [--comment-only] [--dry-run]

The review event follows the selection: REQUEST_CHANGES when a selected finding is blocking,
APPROVE otherwise, COMMENT on your own PR, on a draft, with --comment-only, or when the PR head
moved after it was reviewed. With nothing selected nothing is posted unless --approve asks for a
plain approval. Prints one JSON object whose `outcome` is posted, skipped, no-op or failed.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Set

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clients import CommandError, Gh  # noqa: E402
from findings import Anchor, Event, Finding, FindingsError, label, read_json  # noqa: E402
from ledger import Dirs, Disposition, Ledger, LedgerError, state_root  # noqa: E402


class SelectionError(Exception):
    """The --select value is not all, none, or a list of finding numbers that exist."""


def parse_selection(text: str, findings: List[Finding]) -> Set[int]:
    """Raises SelectionError on anything but all, none, or known finding numbers."""
    known = {f.number for f in findings}
    word = text.strip().lower()
    if word == "all":
        return known
    if word == "none":
        return set()
    try:
        chosen = {int(part) for part in word.replace(" ", "").split(",") if part}
    except ValueError:
        raise SelectionError(f"'{text}' is not all, none, or a comma-separated list of numbers") from None
    unknown = sorted(chosen - known)
    if unknown or not chosen:
        raise SelectionError(f"no finding numbered {', '.join(map(str, unknown)) or text}; there are {len(known)}")
    return chosen


def decide_event(selected: List[Finding], *, own_pr: bool, draft: bool, head_moved: bool, comment_only: bool) -> Event:
    if own_pr or draft or head_moved or comment_only:
        return Event.COMMENT
    return Event.REQUEST_CHANGES if any(f.blocking for f in selected) else Event.APPROVE


def comment_body(finding: Finding, with_suggestion: bool) -> str:
    parts = [f"**{label(finding)}** · {finding.category.value}", "", f"**{finding.title}**", "", finding.body]
    if with_suggestion and finding.suggestion:
        parts += ["", "```suggestion", finding.suggestion.rstrip("\n"), "```"]
    return "\n".join(parts)


def inline_comment(finding: Finding) -> dict:
    comment = {"path": finding.file, "line": finding.line, "side": "RIGHT", "body": comment_body(finding, True)}
    if finding.start_line is not None:
        comment.update(start_line=finding.start_line, start_side="RIGHT")
    return comment


def review_body(plan: dict, summary: str, selected: List[Finding], in_body: List[Finding], event: Event,
                notes: List[str]) -> str:
    lines = [summary, ""] if summary else []
    if not selected:
        lines.append("No issues found." if event is Event.APPROVE else "No comments.")
    else:
        blocking = sum(f.blocking for f in selected)
        lines.append(f"**{len(selected)} comment(s)**, {blocking} blocking.")
    for finding in in_body:
        lines += ["", f"### `{finding.file}:{finding.line}`", "", comment_body(finding, False)]
    lines += ["", f"<sub>Reviewed at {plan['head'][:9]} ({plan['mode']} review)."
              + "".join(f" {note}" for note in notes) + "</sub>"]
    return "\n".join(lines)


def build_payload(plan: dict, summary: str, selected: List[Finding], event: Event, notes: List[str],
                  inline: bool = True) -> dict:
    inline_findings = [f for f in selected if inline and f.anchor is Anchor.INLINE]
    in_body = [f for f in selected if f not in inline_findings]
    payload = {"commit_id": plan["head"], "event": event.value,
               "body": review_body(plan, summary, selected, in_body, event, notes)}
    if inline_findings:
        payload["comments"] = [inline_comment(f) for f in inline_findings]
    return payload


def send(gh: Gh, plan: dict, payload_path: Path, summary: str, selected: List[Finding], event: Event,
         notes: List[str]) -> str:
    """The review URL. Retries once with every comment in the review body when GitHub refuses the inline anchors."""
    payload = build_payload(plan, summary, selected, event, notes)
    payload_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        return gh.post_review(plan["repo"], plan["pr"], str(payload_path))
    except CommandError as first:
        if "comments" not in payload:
            raise
        notes.append("Inline anchors were refused, so every comment is in this body.")
        fallback = build_payload(plan, summary, selected, event, notes, inline=False)
        payload_path.write_text(json.dumps(fallback, indent=2), encoding="utf-8")
        try:
            return gh.post_review(plan["repo"], plan["pr"], str(payload_path))
        except CommandError as second:
            raise CommandError(f"{first}; retry without inline comments also failed: {second}") from None


def close_ledger(ledger: Ledger, plan: dict, findings: List[Finding], chosen: Set[int], event: Optional[Event],
                 url: Optional[str]) -> None:
    for finding in findings:
        if finding.number in chosen:
            ledger.set_disposition(finding.ledger_key, Disposition.POSTED, f"posted in {url}")
        else:
            ledger.set_disposition(finding.ledger_key, Disposition.DECLINED, "the reviewer chose not to post it")
    ledger.close_pass(plan["head"], posted=len(chosen), verdict=event.value if event else None, review_url=url)
    ledger.save()


def post(repo: str, pr: int, selection: str, *, gh: Gh, root: Path, approve: bool = False, comment_only: bool = False,
         dry_run: bool = False) -> dict:
    """Raises FindingsError, SelectionError, LedgerError or CommandError; nothing is recorded when posting fails."""
    dirs = Dirs(root, repo, pr)
    plan = read_json(dirs.run / "plan.json")
    stored = read_json(dirs.run / "findings.json")
    findings = [Finding.from_json(item) for item in stored.get("findings") or []]
    chosen = parse_selection(selection, findings)
    selected = [f for f in findings if f.number in chosen]
    ledger = Ledger.load(dirs.ledger)

    if not selected and not approve:
        if not dry_run:
            close_ledger(ledger, plan, findings, chosen, None, None)
        return {"status": "ok", "outcome": "skipped" if findings else "no-op", "posted": 0, "event": None, "url": None}

    notes: List[str] = []
    head_moved = gh.pr_head(repo, pr) != plan["head"]
    if head_moved:
        notes.append("The PR head moved after this review, so it is a comment, not a verdict on the new commits.")
    event = decide_event(selected, own_pr=plan.get("own_pr", False), draft=plan.get("draft", False),
                         head_moved=head_moved, comment_only=comment_only)
    summary = str(stored.get("summary") or "")
    if dry_run:
        return {"status": "ok", "outcome": "skipped", "dry_run": True, "event": event.value,
                "payload": build_payload(plan, summary, selected, event, notes)}
    url = send(gh, plan, dirs.run / "review.json", summary, selected, event, notes)
    close_ledger(ledger, plan, findings, chosen, event, url)
    return {"status": "ok", "outcome": "posted", "posted": len(selected), "event": event.value, "url": url,
            "notes": notes}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo")
    parser.add_argument("pr", type=int)
    parser.add_argument("--select", required=True, help="all, none, or finding numbers such as 1,3,5")
    parser.add_argument("--approve", action="store_true", help="with nothing selected, post a plain approval")
    parser.add_argument("--comment-only", action="store_true", help="never approve or request changes")
    parser.add_argument("--dry-run", action="store_true", help="print the payload and post nothing")
    args = parser.parse_args(argv)
    try:
        result = post(args.repo, args.pr, args.select, gh=Gh(), root=state_root(), approve=args.approve,
                      comment_only=args.comment_only, dry_run=args.dry_run)
    except (FindingsError, SelectionError, LedgerError, CommandError) as exc:
        print(json.dumps({"status": "error", "outcome": "failed", "error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
