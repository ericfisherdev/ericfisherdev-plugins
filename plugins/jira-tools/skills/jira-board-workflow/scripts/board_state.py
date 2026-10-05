#!/usr/bin/env python3
"""Compact Kanban-board queue state for the jira-board-workflow skill.

The board analogue of jira-sprint-workflow's sprint_state.py, for projects whose board
has no sprints. Prints everything the orchestrator needs to decide what to do next in
one small table, so the main session never has to page through Jira JSON.

Usage:
  board_state.py PROJECT                          # whole board, guardrailed
  board_state.py PROJECT --epic FWDF-179          # one epic's children
  board_state.py PROJECT --label security         # one label
  board_state.py PROJECT --keys FWDF-162,FWDF-163 # an explicit set
  board_state.py PROJECT --jql "..."              # anything else
  board_state.py PROJECT --json                   # machine-readable

Archived tickets are excluded structurally: the queue is read from the board's own
issue endpoint, which never contains archived issues. See ARCHIVED_NOTE below for why
this is not done with a JQL clause.

Environment: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN
"""

import argparse
import json
import sys
import urllib.parse

from jira_queue import QUEUE_FIELDS, api, build_rows, print_table, summarize

# Do NOT add `archivedDate IS EMPTY` (or archivedBy) to any JQL built here. On instances
# without Jira's Premium archiving feature those clauses match nothing at all -- both
# `IS EMPTY` and `IS NOT EMPTY` return zero issues -- so the queue silently comes back
# empty. Archived issues are excluded by reading from the board endpoint instead, with
# drop_archived() as a defensive second layer for instances that do expose the fields.
ARCHIVED_NOTE = "archived excluded via board endpoint (never via JQL)"

PAGE_SIZE = 50
DEFAULT_MAX_QUEUE = 12


def resolve_board(project, board_id):
    """Return the board id to read, refusing to guess between several."""
    boards = api(f"/rest/agile/1.0/board?projectKeyOrId={project}").get("values", [])
    if not boards:
        sys.exit(f"No board found for project {project}")
    if board_id:
        match = [b for b in boards if str(b["id"]) == str(board_id)]
        if not match:
            listing = ", ".join(f"{b['id']} ({b['name']})" for b in boards)
            sys.exit(f"Board {board_id} is not a board of {project}. Boards: {listing}")
        return match[0]
    if len(boards) > 1:
        listing = ", ".join(f"{b['id']} ({b['name']})" for b in boards)
        sys.exit(f"{project} has several boards; pass --board. Boards: {listing}")
    return boards[0]


def build_jql(args):
    """AND the always-on clauses with whichever scope flag was given."""
    # Issue-type filtering is done client-side in drop_containers(), not here: issue
    # type names vary per instance ('Sub-task' does not exist in every project and JQL
    # 400s on an unknown one), while the issuetype payload's hierarchyLevel/subtask
    # flags are always present.
    clauses = ["statusCategory != Done"]

    if args.epic:
        # Team-managed projects use `parent`; "Epic Link" does not exist and 400s.
        clauses.append(f'parent = "{args.epic}"')
    if args.label:
        clauses.append(f'labels = "{args.label}"')
    if args.keys:
        keys = ", ".join(k.strip() for k in args.keys.split(",") if k.strip())
        if not keys:
            sys.exit("--keys was empty")
        clauses.append(f"key in ({keys})")
    if args.jql:
        clauses.append(f"({args.jql})")

    return " AND ".join(clauses) + " ORDER BY key ASC"


def fetch_board_issues(board, jql):
    """All issues on the board matching jql, following startAt paging."""
    issues = []
    start = 0
    while True:
        query = urllib.parse.urlencode({
            "jql": jql,
            "fields": QUEUE_FIELDS,
            "startAt": start,
            "maxResults": PAGE_SIZE,
        })
        page = api(f"/rest/agile/1.0/board/{board}/issue?{query}")
        batch = page.get("issues", [])
        issues.extend(batch)
        start += len(batch)
        if not batch or start >= page.get("total", 0):
            return issues


def drop_archived(issues):
    """Second layer of archived exclusion, for instances that expose the fields.

    A no-op where Jira does not surface archivedDate/archivedBy (they are simply absent
    from the response), which is why the board endpoint is the real guarantee.
    """
    return [
        i for i in issues
        if not i["fields"].get("archivedDate") and not i["fields"].get("archivedBy")
    ]


def drop_containers(issues):
    """Keep only workable tickets: no sub-tasks, no epics or higher.

    hierarchyLevel is 0 for ordinary work items, negative for sub-tasks, positive for
    epics and above.
    """
    kept = []
    for issue in issues:
        issuetype = issue["fields"]["issuetype"]
        if issuetype.get("subtask"):
            continue
        if issuetype.get("hierarchyLevel", 0) != 0:
            continue
        kept.append(issue)
    return kept


def scope_label(args):
    parts = []
    if args.epic:
        parts.append(f"epic {args.epic}")
    if args.label:
        parts.append(f"label {args.label}")
    if args.keys:
        parts.append("explicit keys")
    if args.jql:
        parts.append("custom jql")
    return ", ".join(parts) if parts else "whole board"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--board", help="board id (required when the project has several)")
    parser.add_argument("--epic", help="only children of this epic key")
    parser.add_argument("--label", help="only issues carrying this label")
    parser.add_argument("--keys", help="comma-separated explicit issue keys")
    parser.add_argument("--jql", help="extra JQL, ANDed with the rest")
    parser.add_argument("--include-epics", action="store_true",
                        help="keep Epics and Sub-tasks in the queue")
    parser.add_argument("--max-queue", type=int, default=DEFAULT_MAX_QUEUE,
                        help=f"unscoped queue size that trips the guardrail "
                             f"(default {DEFAULT_MAX_QUEUE})")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    board = resolve_board(args.project, args.board)
    jql = build_jql(args)
    issues = drop_archived(fetch_board_issues(board["id"], jql))
    if not args.include_epics:
        issues = drop_containers(issues)
    scope = scope_label(args)

    # A board has no natural size the way a sprint does. Starting a sequential run over
    # everything open is almost never what the caller meant, so make them say so.
    scoped = bool(args.epic or args.label or args.keys or args.jql)
    if not scoped and len(issues) > args.max_queue:
        sys.exit(
            f"{len(issues)} open tickets on board {board['id']} ({board['name']}) exceeds "
            f"--max-queue {args.max_queue} and no scope was given.\n"
            f"Narrow with --epic KEY, --label L, --keys K1,K2, or --jql, or raise "
            f"--max-queue deliberately."
        )

    rows = build_rows(issues)
    state = summarize(rows)
    state.update({
        "project": args.project,
        "board": {"id": board["id"], "name": board["name"], "type": board["type"]},
        "scope": scope,
        "jql": jql,
        "archived": ARCHIVED_NOTE,
    })

    if args.as_json:
        print(json.dumps(state, indent=1))
        return

    print(f"{board['name']}  (board {board['id']}, {board['type']}, "
          f"project {args.project})")
    print(f"scope: {scope}  --  {len(rows)} tickets, {ARCHIVED_NOTE}")
    print_table(rows, state)


if __name__ == "__main__":
    main()
