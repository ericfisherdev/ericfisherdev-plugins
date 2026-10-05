#!/usr/bin/env python3
"""Shared Jira queue primitives for the jira-board-workflow skill.

Holds the pieces that describe a work queue independently of where the queue came
from: the authenticated GET, the "what blocks this" link reading, and the row and
verdict computation the orchestrator prints.

Known duplication: jira-sprint-workflow/scripts/sprint_state.py still carries its own
copies of api() and blockers_of(). That script works and is deliberately left alone;
folding it onto this module is a separate change.

Environment: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request

POINTS_FIELD = "customfield_10016"  # "Story point estimate"
WORKFLOW_ORDER = ["To Do", "Plan Created", "In Progress", "In Review", "Done"]

# Fields every queue row needs. archivedDate/archivedBy are requested so the archived
# post-filter in board_state.py has something to read on instances that expose them;
# Jira omits unknown fields rather than erroring, so this is safe everywhere.
QUEUE_FIELDS = (
    "summary,status,assignee,issuetype,parent,labels,issuelinks,"
    f"{POINTS_FIELD},archivedDate,archivedBy"
)


def api(path):
    """GET a Jira REST path and return parsed JSON, or exit with a one-line error."""
    base = os.environ["JIRA_BASE_URL"].rstrip("/")
    req = urllib.request.Request(base + path)
    req.add_header("Accept", "application/json")
    token = f"{os.environ['JIRA_EMAIL']}:{os.environ['JIRA_API_TOKEN']}"
    req.add_header("Authorization", "Basic " + base64.b64encode(token.encode()).decode())
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()[:200].decode(errors="replace")
        sys.exit(f"Jira API {exc.code} on {path}: {body}")
    except urllib.error.URLError as exc:
        sys.exit(f"Jira unreachable at {base}: {exc.reason}")


def issue_number(key):
    """Numeric part of an issue key, for lowest-first ordering."""
    try:
        return int(key.split("-")[1])
    except (IndexError, ValueError):
        return 0


def blockers_of(issue):
    """(key, status) pairs for the issues that block this one.

    On issue X, a 'Blocks' link carrying inwardIssue means X is blocked by that issue.
    The create-side API swaps inward/outward from what the docs imply; this is the read
    side, which matches what the Jira UI displays.
    """
    out = []
    for link in issue["fields"].get("issuelinks") or []:
        if (link.get("type") or {}).get("name") != "Blocks":
            continue
        blocker = link.get("inwardIssue")
        if blocker:
            out.append((blocker["key"], blocker["fields"]["status"]["name"]))
    return out


def build_rows(issues):
    """One row per issue, lowest key number first, with blocker analysis resolved."""
    in_queue = {i["key"] for i in issues}
    rows = []
    for issue in sorted(issues, key=lambda i: issue_number(i["key"])):
        fields = issue["fields"]
        unmet = [(k, s) for k, s in blockers_of(issue) if s != "Done"]
        assignee = fields.get("assignee") or {}
        rows.append({
            "key": issue["key"],
            "summary": fields["summary"],
            "status": fields["status"]["name"],
            "type": fields["issuetype"]["name"],
            "points": fields.get(POINTS_FIELD),
            "assignee": assignee.get("displayName"),
            "blocked_by": [k for k, _ in unmet],
            # A blocker outside the queue cannot be resolved by this run.
            "external_blockers": [k for k, _ in unmet if k not in in_queue],
        })
    return rows


def summarize(rows):
    """Verdict fields the orchestrator branches on."""
    not_planned = [r["key"] for r in rows if r["status"] == "To Do"]
    unpointed = [r["key"] for r in rows if r["points"] in (None, 0)]
    unassigned = [r["key"] for r in rows if not r["assignee"] and r["status"] != "To Do"]
    actionable = [
        r["key"] for r in rows
        if r["status"] == "Plan Created" and not r["blocked_by"]
    ]
    return {
        "issues": rows,
        "not_planned": not_planned,
        "unpointed": unpointed,
        "unassigned": unassigned,
        "external_blockers": sorted({k for r in rows for k in r["external_blockers"]}),
        "in_flight": [r["key"] for r in rows if r["status"] in ("In Progress", "In Review")],
        "actionable": actionable,
        "done": [r["key"] for r in rows if r["status"] == "Done"],
        "planning_complete": not not_planned and not unpointed,
        "next_ticket": actionable[0] if actionable else None,
    }


def print_table(rows, state):
    """The whole point of these scripts: one small table plus a verdict."""
    print(f"{'KEY':<10} {'STATUS':<13} {'PTS':>3}  {'BLOCKED-BY':<12} SUMMARY")
    for row in rows:
        blocked = ",".join(row["blocked_by"]) or "-"
        points = row["points"] if row["points"] is not None else "-"
        print(
            f"{row['key']:<10} {row['status']:<13} {str(points):>3}  "
            f"{blocked:<12} {row['summary'][:44]}"
        )

    print()
    print(
        f"planning complete : {state['planning_complete']}"
        f"   (To Do: {len(state['not_planned'])}, unpointed: {len(state['unpointed'])})"
    )
    if state["external_blockers"]:
        print("!! EXTERNAL BLOCKERS (not Done, not in queue): "
              + ", ".join(state["external_blockers"]))
    if state["in_flight"]:
        print("!! IN FLIGHT (finish or reset before starting new work): "
              + ", ".join(state["in_flight"]))
    if state["unassigned"]:
        print("!! UNASSIGNED past To Do (assignment invariant broken): "
              + ", ".join(state["unassigned"]))
    print(f"done              : {len(state['done'])}/{len(rows)}")
    print(f"next ticket       : {state['next_ticket'] or '(none actionable)'}")
