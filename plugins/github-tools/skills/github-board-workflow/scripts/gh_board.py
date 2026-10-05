#!/usr/bin/env python3
"""GitHub Projects queue state and mutations for the github-board-workflow skill.

The GitHub analogue of jira-board-workflow/scripts/board_state.py. Prints everything the
orchestrator needs to decide what to do next in one small table, and gives subagents a
single command for advancing an issue, so nobody in the run has to juggle project item
ids, field ids, or single-select option ids.

Usage:
  gh_board.py state OWNER/REPO --project N [scope] [--include-parents] [--max-queue 12] [--json]
      scope: --parent N | --label L | --issues 1,2,3 | --workstream NAME | --search "..."
  gh_board.py set OWNER/REPO --project N ISSUE [--status S] [--points P] [--assignee LOGIN]
  gh_board.py add OWNER/REPO --project N ISSUE          # put an issue on the board

Concepts, mapped from the Jira skill:
  status      -> the project's built-in "Status" single-select field
                 (Todo -> Plan Created -> In Progress -> In Review -> Done)
  points      -> a project NUMBER field named "Points"
  epic        -> a parent issue; children are its sub-issues
  blocked by  -> GitHub issue dependencies (REST: /issues/N/dependencies/blocked_by)
  container   -> any issue that has sub-issues; dropped from the workable queue

Authentication is whatever `gh` is logged in as. Requires the `project` scope.
"""

import argparse
import json
import subprocess
import sys

WORKFLOW_ORDER = ["Todo", "Plan Created", "In Progress", "In Review", "Done"]
STATUS_FIELD = "Status"
POINTS_FIELD = "Points"
WORKSTREAM_FIELD = "Workstream"
DEFAULT_MAX_QUEUE = 12
PAGE_SIZE = 100


# --------------------------------------------------------------------------- gh plumbing

def gh(*args, input_text=None):
    """Run a gh command and return stdout, or exit with the one decisive stderr line."""
    proc = subprocess.run(
        ["gh", *args], capture_output=True, text=True, input=input_text
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip().splitlines()
        sys.exit(f"gh {' '.join(args[:2])} failed: {err[-1] if err else 'no output'}")
    return proc.stdout


def gh_json(*args):
    out = gh(*args)
    return json.loads(out) if out.strip() else None


def rest(path, method="GET", **fields):
    args = ["api", path, "-X", method] if method != "GET" else ["api", path]
    for key, value in fields.items():
        args += ["-F", f"{key}={value}"]
    return gh_json(*args)


def rest_optional(path):
    """GET that treats 404 as None instead of exiting (parent endpoint on a root issue)."""
    proc = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if proc.returncode != 0:
        if "404" in proc.stderr or "Not Found" in proc.stderr:
            return None
        sys.exit(f"gh api {path} failed: {proc.stderr.strip().splitlines()[-1]}")
    return json.loads(proc.stdout)


def graphql(query, **variables):
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        flag = "-F" if isinstance(value, int) else "-f"
        args += [flag, f"{key}={value}"]
    data = gh_json(*args)
    if data.get("errors"):
        sys.exit("GraphQL: " + data["errors"][0]["message"])
    return data["data"]


# --------------------------------------------------------------------------- project read

PROJECT_QUERY = """
query($owner: String!, $number: Int!, $after: String) {
  %s(login: $owner) {
    projectV2(number: $number) {
      id
      title
      fields(first: 40) {
        nodes {
          ... on ProjectV2FieldCommon { id name dataType }
          ... on ProjectV2SingleSelectField { id name dataType options { id name } }
        }
      }
      items(first: %d, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          fieldValues(first: 20) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name field { ... on ProjectV2FieldCommon { name } }
              }
              ... on ProjectV2ItemFieldNumberValue {
                number field { ... on ProjectV2FieldCommon { name } }
              }
            }
          }
          content {
            ... on Issue {
              id number title state body
              repository { nameWithOwner }
              labels(first: 30) { nodes { name } }
              assignees(first: 5) { nodes { login } }
            }
          }
        }
      }
    }
  }
}
"""


def load_project(owner, number):
    """Project id, field map, and every item, following item paging."""
    project = None
    items = []
    after = None
    for kind in ("user", "organization"):
        query = PROJECT_QUERY % (kind, PAGE_SIZE)
        while True:
            variables = {"owner": owner, "number": number}
            if after:
                variables["after"] = after
            data = graphql(query, **variables)
            node = (data.get(kind) or {}).get("projectV2")
            if node is None:
                break
            project = project or {"id": node["id"], "title": node["title"],
                                  "fields": node["fields"]["nodes"]}
            items.extend(node["items"]["nodes"])
            page = node["items"]["pageInfo"]
            if not page["hasNextPage"]:
                break
            after = page["endCursor"]
        if project:
            break
    if project is None:
        sys.exit(f"No project #{number} owned by {owner} (user or org)")
    return project, items


def field_by_name(project, name):
    for field in project["fields"]:
        if field.get("name") == name:
            return field
    sys.exit(f"Project '{project['title']}' has no field named {name!r}")


def option_id(field, option_name):
    for option in field.get("options", []):
        if option["name"].lower() == option_name.lower():
            return option["id"]
    names = ", ".join(o["name"] for o in field.get("options", []))
    sys.exit(f"Field {field['name']} has no option {option_name!r}. Options: {names}")


def item_values(item):
    """{field name: value} for the single-select and number values an item carries."""
    values = {}
    for value in item["fieldValues"]["nodes"]:
        field = (value.get("field") or {}).get("name")
        if not field:
            continue
        values[field] = value.get("name", value.get("number"))
    return values


# --------------------------------------------------------------------------- issue read

def issue_meta(repo, number):
    """Sub-issue count, open blockers, and parent number for one issue."""
    issue = rest(f"repos/{repo}/issues/{number}")
    blockers = rest(f"repos/{repo}/issues/{number}/dependencies/blocked_by") or []
    parent = rest_optional(f"repos/{repo}/issues/{number}/parent")
    return {
        "children": (issue.get("sub_issues_summary") or {}).get("total", 0),
        "blocked_by": [(b["number"], b["state"]) for b in blockers],
        "parent": parent["number"] if parent else None,
    }


def children_of(repo, parent):
    return {i["number"] for i in rest(f"repos/{repo}/issues/{parent}/sub_issues") or []}


# --------------------------------------------------------------------------- queue

def build_rows(repo, items, project, args):
    """One row per open, workable issue on the board that matches the scope."""
    scope_numbers = None
    if args.parent:
        scope_numbers = children_of(repo, args.parent)
    if args.issues:
        explicit = {int(n) for n in args.issues.split(",") if n.strip()}
        scope_numbers = explicit if scope_numbers is None else scope_numbers & explicit
    if args.search:
        found = gh_json("issue", "list", "-R", repo, "--search", args.search,
                        "--state", "open", "--limit", "200", "--json", "number")
        numbers = {i["number"] for i in found}
        scope_numbers = numbers if scope_numbers is None else scope_numbers & numbers

    candidates = []
    for item in items:
        content = item.get("content") or {}
        if content.get("repository", {}).get("nameWithOwner", "").lower() != repo.lower():
            continue
        if content.get("state") != "OPEN":
            continue
        values = item_values(item)
        status = values.get(STATUS_FIELD) or "Todo"
        if status == "Done":
            continue
        number = content["number"]
        labels = {l["name"] for l in content["labels"]["nodes"]}
        if scope_numbers is not None and number not in scope_numbers:
            continue
        if args.label and args.label not in labels:
            continue
        if args.workstream and (values.get(WORKSTREAM_FIELD) or "").lower() != args.workstream.lower():
            continue
        candidates.append((item, content, values, status, labels))

    rows = []
    for item, content, values, status, labels in candidates:
        meta = issue_meta(repo, content["number"])
        if meta["children"] and not args.include_parents:
            continue
        assignees = [a["login"] for a in content["assignees"]["nodes"]]
        rows.append({
            "number": content["number"],
            "title": content["title"],
            "status": status,
            "points": values.get(POINTS_FIELD),
            "workstream": values.get(WORKSTREAM_FIELD),
            "assignee": assignees[0] if assignees else None,
            "labels": sorted(labels),
            "parent": meta["parent"],
            "blocked_by_all": meta["blocked_by"],
            "item_id": item["id"],
        })

    in_queue = {r["number"] for r in rows}
    for row in sorted(rows, key=lambda r: r["number"]):
        unmet = [n for n, state in row.pop("blocked_by_all") if state == "open"]
        row["blocked_by"] = unmet
        row["external_blockers"] = [n for n in unmet if n not in in_queue]
    return sorted(rows, key=lambda r: r["number"])


def summarize(rows):
    not_planned = [r["number"] for r in rows if r["status"] == "Todo"]
    unpointed = [r["number"] for r in rows if r["points"] in (None, 0)]
    unassigned = [r["number"] for r in rows if not r["assignee"] and r["status"] != "Todo"]
    actionable = [r["number"] for r in rows
                  if r["status"] == "Plan Created" and not r["blocked_by"]]
    return {
        "issues": rows,
        "not_planned": not_planned,
        "unpointed": unpointed,
        "unassigned": unassigned,
        "external_blockers": sorted({n for r in rows for n in r["external_blockers"]}),
        "in_flight": [r["number"] for r in rows if r["status"] in ("In Progress", "In Review")],
        "actionable": actionable,
        "planning_complete": not not_planned and not unpointed,
        "next_issue": actionable[0] if actionable else None,
    }


def print_table(rows, state):
    print(f"{'#':>5} {'STATUS':<13} {'PTS':>3}  {'BLOCKED-BY':<12} {'OWNER':<14} TITLE")
    for row in rows:
        blocked = ",".join(f"#{n}" for n in row["blocked_by"]) or "-"
        points = row["points"]
        if isinstance(points, float) and points.is_integer():
            points = int(points)
        points = "-" if points is None else points
        print(f"{row['number']:>5} {row['status']:<13} {str(points):>3}  "
              f"{blocked:<12} {(row['assignee'] or '-'):<14} {row['title'][:44]}")
    print()
    print(f"planning complete : {state['planning_complete']}"
          f"   (Todo: {len(state['not_planned'])}, unpointed: {len(state['unpointed'])})")
    if state["external_blockers"]:
        print("!! EXTERNAL BLOCKERS (open, not in queue): "
              + ", ".join(f"#{n}" for n in state["external_blockers"]))
    if state["in_flight"]:
        print("!! IN FLIGHT (finish or reset before starting new work): "
              + ", ".join(f"#{n}" for n in state["in_flight"]))
    if state["unassigned"]:
        print("!! UNASSIGNED past Todo (assignment invariant broken): "
              + ", ".join(f"#{n}" for n in state["unassigned"]))
    nxt = f"#{state['next_issue']}" if state["next_issue"] else "(none actionable)"
    print(f"next issue        : {nxt}")


def scope_label(args):
    parts = []
    if args.parent:
        parts.append(f"parent #{args.parent}")
    if args.label:
        parts.append(f"label {args.label}")
    if args.workstream:
        parts.append(f"workstream {args.workstream}")
    if args.issues:
        parts.append("explicit issues")
    if args.search:
        parts.append("search")
    return ", ".join(parts) if parts else "whole board"


# --------------------------------------------------------------------------- commands

def cmd_state(args):
    owner = args.project_owner or args.repo.split("/")[0]
    project, items = load_project(owner, args.project)
    rows = build_rows(args.repo, items, project, args)
    scope = scope_label(args)

    scoped = bool(args.parent or args.label or args.issues or args.search or args.workstream)
    if not scoped and len(rows) > args.max_queue:
        sys.exit(f"{len(rows)} open issues on project #{args.project} ({project['title']}) "
                 f"exceeds --max-queue {args.max_queue} and no scope was given.\n"
                 f"Narrow with --parent N, --label L, --workstream W, --issues a,b, or "
                 f"--search, or raise --max-queue deliberately.")

    state = summarize(rows)
    state.update({"repo": args.repo,
                  "project": {"number": args.project, "id": project["id"],
                              "title": project["title"], "owner": owner},
                  "scope": scope})
    if args.as_json:
        print(json.dumps(state, indent=1))
        return
    print(f"{project['title']}  (project #{args.project}, owner {owner}, repo {args.repo})")
    print(f"scope: {scope}  --  {len(rows)} issues")
    print_table(rows, state)


def find_item(items, repo, number):
    for item in items:
        content = item.get("content") or {}
        if (content.get("number") == number
                and content.get("repository", {}).get("nameWithOwner", "").lower() == repo.lower()):
            return item["id"]
    return None


def ensure_item(args, project, items):
    item_id = find_item(items, args.repo, args.issue)
    if item_id:
        return item_id
    url = f"https://github.com/{args.repo}/issues/{args.issue}"
    added = gh_json("project", "item-add", str(args.project), "--owner",
                    args.project_owner or args.repo.split("/")[0],
                    "--url", url, "--format", "json")
    return added["id"]


def cmd_add(args):
    owner = args.project_owner or args.repo.split("/")[0]
    project, items = load_project(owner, args.project)
    item_id = ensure_item(args, project, items)
    print(f"#{args.issue} on project #{args.project} as {item_id}")


def cmd_set(args):
    if not (args.status or args.points is not None or args.assignee):
        sys.exit("set: nothing to do; pass --status, --points, and/or --assignee")
    owner = args.project_owner or args.repo.split("/")[0]
    project, items = load_project(owner, args.project)
    item_id = ensure_item(args, project, items)
    done = []

    # Assignee first so a status transition never lands unassigned.
    if args.assignee:
        gh("issue", "edit", str(args.issue), "-R", args.repo, "--add-assignee", args.assignee)
        done.append(f"assignee={args.assignee}")

    if args.points is not None:
        field = field_by_name(project, POINTS_FIELD)
        gh("project", "item-edit", "--project-id", project["id"], "--id", item_id,
           "--field-id", field["id"], "--number", str(args.points))
        done.append(f"points={args.points}")

    if args.status:
        field = field_by_name(project, STATUS_FIELD)
        canonical = next((s for s in WORKFLOW_ORDER if s.lower() == args.status.lower()), None)
        if canonical is None:
            sys.exit(f"Unknown status {args.status!r}. Use one of: {', '.join(WORKFLOW_ORDER)}")
        gh("project", "item-edit", "--project-id", project["id"], "--id", item_id,
           "--field-id", field["id"], "--single-select-option-id", option_id(field, canonical))
        done.append(f"status={canonical}")
        if canonical == "Done":
            issue = rest(f"repos/{args.repo}/issues/{args.issue}")
            if issue["state"] == "open":
                gh("issue", "close", str(args.issue), "-R", args.repo, "--reason", "completed")
                done.append("closed")

    print(f"#{args.issue}: " + ", ".join(done))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("repo", help="OWNER/REPO")
        p.add_argument("--project", type=int, required=True, help="project number")
        p.add_argument("--project-owner", help="project owner login if not the repo owner")

    s = sub.add_parser("state", help="print queue table and verdict")
    common(s)
    s.add_argument("--parent", type=int, help="only sub-issues of this issue")
    s.add_argument("--label", help="only issues carrying this label")
    s.add_argument("--workstream", help="only items whose Workstream field equals this")
    s.add_argument("--issues", help="comma-separated explicit issue numbers")
    s.add_argument("--search", help="gh issue list --search query, intersected with the board")
    s.add_argument("--include-parents", action="store_true",
                   help="keep issues that have sub-issues in the queue")
    s.add_argument("--max-queue", type=int, default=DEFAULT_MAX_QUEUE)
    s.add_argument("--json", action="store_true", dest="as_json")
    s.set_defaults(func=cmd_state)

    t = sub.add_parser("set", help="set status, points, and/or assignee on one issue")
    common(t)
    t.add_argument("issue", type=int)
    t.add_argument("--status", help="|".join(WORKFLOW_ORDER))
    t.add_argument("--points", type=int)
    t.add_argument("--assignee", help="GitHub login")
    t.set_defaults(func=cmd_set)

    a = sub.add_parser("add", help="add an issue to the project board")
    common(a)
    a.add_argument("issue", type=int)
    a.set_defaults(func=cmd_add)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
