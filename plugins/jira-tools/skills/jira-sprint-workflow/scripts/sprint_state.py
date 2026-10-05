#!/usr/bin/env python3
"""Compact sprint state for the jira-sprint-workflow skill.

Prints everything the orchestrator needs to decide what to do next, in one small
table, so the main session never has to page through Jira JSON. Context economy is
the whole point: this replaces a dozen API calls and their payloads with ~20 lines.

Usage:
  sprint_state.py PROJECT                 # active sprint, else first future sprint
  sprint_state.py PROJECT --sprint 778    # a specific sprint id
  sprint_state.py PROJECT --json          # machine-readable

Environment: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

POINTS_FIELD = "customfield_10016"  # "Story point estimate"
WORKFLOW_ORDER = ["To Do", "Plan Created", "In Progress", "In Review", "Done"]


def api(path):
    base = os.environ["JIRA_BASE_URL"].rstrip("/")
    req = urllib.request.Request(base + path)
    req.add_header("Accept", "application/json")
    token = f"{os.environ['JIRA_EMAIL']}:{os.environ['JIRA_API_TOKEN']}"
    req.add_header("Authorization", "Basic " + base64.b64encode(token.encode()).decode())
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        sys.exit(f"Jira API {exc.code} on {path}: {exc.read()[:200].decode(errors='replace')}")


def resolve_sprint(project, sprint_id):
    """Return (sprint dict, board id). Prefers active, falls back to earliest future."""
    boards = api(f"/rest/agile/1.0/board?projectKeyOrId={project}").get("values", [])
    if not boards:
        sys.exit(f"No board found for project {project}")
    board = boards[0]["id"]

    sprints = api(f"/rest/agile/1.0/board/{board}/sprint").get("values", [])
    if sprint_id:
        match = [s for s in sprints if str(s["id"]) == str(sprint_id)]
        if not match:
            sys.exit(f"Sprint {sprint_id} not found on board {board}")
        return match[0], board

    active = [s for s in sprints if s["state"] == "active"]
    if active:
        return active[0], board
    future = [s for s in sprints if s["state"] == "future"]
    if not future:
        sys.exit(f"No active or future sprint on board {board}")
    return sorted(future, key=lambda s: s["id"])[0], board


def blockers_of(issue):
    """Keys that block this issue.

    On issue X, a 'Blocks' link carrying inwardIssue means X is blocked by that
    issue. Note the create-side API swaps inward/outward from what the docs imply;
    this is the read side, which matches what the Jira UI displays.
    """
    out = []
    for link in issue["fields"].get("issuelinks") or []:
        if (link.get("type") or {}).get("name") != "Blocks":
            continue
        blocker = link.get("inwardIssue")
        if blocker:
            out.append((blocker["key"], (blocker["fields"]["status"]["name"])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--sprint", help="sprint id (default: active, else earliest future)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    sprint, board = resolve_sprint(args.project, args.sprint)
    fields = f"summary,status,{POINTS_FIELD},issuelinks,issuetype,parent"
    issues = api(
        f"/rest/agile/1.0/sprint/{sprint['id']}/issue?maxResults=200&fields={fields}"
    ).get("issues", [])

    in_sprint = {i["key"] for i in issues}
    rows = []
    for issue in sorted(issues, key=lambda i: int(i["key"].split("-")[1])):
        f = issue["fields"]
        blockers = blockers_of(issue)
        # A blocker is satisfied if it is Done; otherwise it must at least be in
        # this sprint, or the sprint is not self-contained and planning is wrong.
        unmet = [(k, s) for k, s in blockers if s != "Done"]
        external = [(k, s) for k, s in unmet if k not in in_sprint]
        rows.append({
            "key": issue["key"],
            "summary": f["summary"],
            "status": f["status"]["name"],
            "points": f.get(POINTS_FIELD),
            "blocked_by": [k for k, _ in unmet],
            "external_blockers": [k for k, _ in external],
        })

    unpointed = [r["key"] for r in rows if r["points"] in (None, 0)]
    not_planned = [r["key"] for r in rows if r["status"] == "To Do"]
    external = sorted({k for r in rows for k in r["external_blockers"]})
    actionable = [
        r["key"] for r in rows
        if r["status"] == "Plan Created" and not r["blocked_by"]
    ]
    in_flight = [r["key"] for r in rows if r["status"] in ("In Progress", "In Review")]
    done = [r["key"] for r in rows if r["status"] == "Done"]

    state = {
        "project": args.project,
        "board": board,
        "sprint": {"id": sprint["id"], "name": sprint["name"], "state": sprint["state"]},
        "issues": rows,
        "not_planned": not_planned,
        "unpointed": unpointed,
        "external_blockers": external,
        "in_flight": in_flight,
        "actionable": actionable,
        "done": done,
        "planning_complete": not not_planned and not unpointed,
        "next_ticket": actionable[0] if actionable else None,
    }

    if args.as_json:
        print(json.dumps(state, indent=1))
        return

    print(f"{sprint['name']}  (id {sprint['id']}, {sprint['state']}, board {board})")
    print(f"{'KEY':<10} {'STATUS':<13} {'PTS':>3}  BLOCKED-BY   SUMMARY")
    for r in rows:
        blocked = ",".join(r["blocked_by"]) or "-"
        pts = r["points"] if r["points"] is not None else "-"
        print(f"{r['key']:<10} {r['status']:<13} {str(pts):>3}  {blocked:<12} {r['summary'][:44]}")

    print()
    print(f"planning complete : {state['planning_complete']}"
          f"   (To Do: {len(not_planned)}, unpointed: {len(unpointed)})")
    if external:
        print(f"!! EXTERNAL BLOCKERS (not Done, not in sprint): {', '.join(external)}")
    if in_flight:
        print(f"!! IN FLIGHT (finish or reset before starting new work): {', '.join(in_flight)}")
    print(f"done              : {len(done)}/{len(rows)}")
    print(f"next ticket       : {state['next_ticket'] or '(none actionable)'}")


if __name__ == "__main__":
    main()
