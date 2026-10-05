#!/usr/bin/env python3
"""Compact Plane project state for the plane-task-workflow skill.

The orchestrator never pages through Plane JSON. This prints one small table plus
a verdict, and wraps the two mutations a run needs (move state, assign) so no
subagent has to resolve a state UUID by hand.

Usage:
  plane_state.py state READ                     # roll-up table + next task
  plane_state.py state READ --json              # machine-readable
  plane_state.py state READ --epic READ-14      # only tasks under one epic
  plane_state.py show READ-16                   # one work item, body included
  plane_state.py move READ-16 "In Progress"     # transition
  plane_state.py move READ-16 Done --assign eric
  plane_state.py update-plan READ-16 --file plan.md   # replace only the Implementation Plan

Config, env first then fallback:
  PLANE_BASE_URL   default http://192.168.0.16:8090
  PLANE_WORKSPACE  default ericfisherdev
  PLANE_API_KEY    else the contents of ~/.plane_token
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("PLANE_BASE_URL", "http://192.168.0.16:8090").rstrip("/")
WORKSPACE = os.environ.get("PLANE_WORKSPACE", "ericfisherdev")
TOKEN_FILE = os.path.expanduser("~/.plane_token")

# State groups Plane ships with. Names are user-editable; groups are not, so all
# classification keys off the group and never off the display name.
NOT_STARTED = ("backlog", "unstarted")
IN_FLIGHT = ("started",)
FINISHED = ("completed",)
ABANDONED = ("cancelled",)

# A task carrying this label needs a person before it can move. The workflow
# stops the whole run when one appears rather than working around it.
WAITING_LABEL = "needs-human"


def token():
    key = os.environ.get("PLANE_API_KEY")
    if key:
        return key.strip()
    if os.path.exists(TOKEN_FILE):
        return open(TOKEN_FILE).read().strip()
    sys.exit("No Plane API key: set PLANE_API_KEY or write one to ~/.plane_token")


def api(path, method="GET", payload=None, _attempt=0):
    req = urllib.request.Request(
        f"{BASE}/api/v1{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
    )
    req.add_header("X-API-Key", token())
    req.add_header("Accept", "application/json")
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        # Plane rate-limits API keys (the stack sets API_KEY_RATE_LIMIT=60/minute).
        # A run that transitions several items can trip it, so back off rather than
        # dying halfway through and leaving a work item mid-transition.
        if exc.code == 429 and _attempt < 3:
            time.sleep(20 * (_attempt + 1))
            return api(path, method, payload, _attempt + 1)
        detail = exc.read()[:200].decode(errors="replace")
        if exc.code == 429:
            sys.exit(f"Plane rate limit still hitting after retries on {path}. "
                     f"Wait a minute and re-run.")
        sys.exit(f"Plane API {exc.code} on {path}: {detail}")
    except urllib.error.URLError as exc:
        sys.exit(f"Cannot reach Plane at {BASE}: {exc.reason}")


def paginate(path):
    """Plane uses cursor pagination; follow it to the end."""
    out, cursor = [], None
    while True:
        sep = "&" if "?" in path else "?"
        url = f"{path}{sep}per_page=100" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
        page = api(url)
        out.extend(page.get("results", []))
        if not page.get("next_page_results"):
            return out
        cursor = page.get("next_cursor")


def resolve_project(identifier):
    for p in paginate(f"/workspaces/{WORKSPACE}/projects/"):
        if p.get("identifier", "").upper() == identifier.upper():
            return p
    sys.exit(f"No project with identifier {identifier} in workspace {WORKSPACE}")


def resolve_state(project_id, name):
    states = paginate(f"/workspaces/{WORKSPACE}/projects/{project_id}/states/")
    for s in states:
        if s["name"].lower() == name.lower():
            return s
    for s in states:  # allow a group name as a convenience
        if s["group"].lower() == name.lower():
            return s
    known = ", ".join(sorted(s["name"] for s in states))
    sys.exit(f"No state named {name!r}. Available: {known}")


def resolve_member(needle):
    members = api(f"/workspaces/{WORKSPACE}/members/")
    members = members if isinstance(members, list) else members.get("results", [])
    needle = needle.lower()
    for m in members:
        haystack = f"{m.get('display_name','')} {m.get('email','')}".lower()
        if needle in haystack:
            return m
    sys.exit(f"No workspace member matching {needle!r}")


def fetch_by_key(key):
    """READ-16 -> the work item dict. Plane resolves this route natively."""
    if not re.fullmatch(r"[A-Za-z]+-\d+", key):
        sys.exit(f"Not a work item key: {key!r} (expected e.g. READ-16)")
    return api(f"/workspaces/{WORKSPACE}/issues/{key.upper()}/")


def blockers_for(project_id, item_id):
    """Work item ids blocking this item.

    The endpoint returns relations already grouped by type, and each entry is
    {"project_id": ..., "issue_id": ...} — note `issue_id`, not `id`. Reading the
    wrong key here fails silently: no blocker is ever reported and the workflow
    happily picks up a blocked task.
    """
    rel = api(f"/workspaces/{WORKSPACE}/projects/{project_id}/work-items/{item_id}/relations/")
    entries = rel.get("blocked_by", []) if isinstance(rel, dict) else (rel or [])
    return [e["issue_id"] for e in entries if isinstance(e, dict) and e.get("issue_id")]


# ------------------------------------------------------------------ state ----
def cmd_state(args):
    project = resolve_project(args.project)
    pid = project["id"]
    ident = project["identifier"]

    states = {s["id"]: s for s in paginate(f"/workspaces/{WORKSPACE}/projects/{pid}/states/")}
    labels = {l["id"]: l["name"] for l in paginate(f"/workspaces/{WORKSPACE}/projects/{pid}/labels/")}
    items = paginate(f"/workspaces/{WORKSPACE}/projects/{pid}/work-items/")

    def labels_of(item):
        return sorted(labels.get(lid, lid) for lid in (item.get("labels") or []))

    def kind_of(item):
        # `doc` routes to the document-task prompt. Unlike assignees, labels are
        # readable on v1, so this is decidable without asking the planner.
        return "document" if "doc" in labels_of(item) else "code"

    def waiting_on_human(item):
        # A task that cannot progress without a person. The run HALTS on these
        # rather than skipping past them, so they must never enter the queue.
        return WAITING_LABEL in labels_of(item)

    by_id = {i["id"]: i for i in items}
    epics = [i for i in items if not i.get("parent")]
    tasks = [i for i in items if i.get("parent")]

    def group_of(item):
        st = states.get(item.get("state"))
        return st["group"] if st else "unknown"

    if args.epic:
        target = fetch_by_key(args.epic)
        tasks = [t for t in tasks if t["parent"] == target["id"]]
        epics = [e for e in epics if e["id"] == target["id"]]

    def key_of(item):
        return f"{ident}-{item['sequence_id']}"

    waiting = [t for t in tasks if waiting_on_human(t) and group_of(t) not in FINISHED]
    waiting_ids = {t["id"] for t in waiting}

    todo = [t for t in tasks if group_of(t) in NOT_STARTED and t["id"] not in waiting_ids]
    wip = [t for t in tasks if group_of(t) in IN_FLIGHT and t["id"] not in waiting_ids]
    done = [t for t in tasks if group_of(t) in FINISHED]
    cancelled = [t for t in tasks if group_of(t) in ABANDONED]

    todo.sort(key=lambda t: t["sequence_id"])
    waiting.sort(key=lambda t: t["sequence_id"])

    # Relation lookups are one call each, so only probe the head of the queue.
    candidates, blocked = [], []
    for t in todo[: args.probe]:
        unmet = []
        for bid in blockers_for(pid, t["id"]):
            other = by_id.get(bid)
            if other is None:
                # A blocker outside this project (or archived). Cannot judge it, so
                # treat it as unmet rather than assuming it is finished.
                unmet.append(f"external:{bid[:8]}")
            elif group_of(other) not in FINISHED:
                unmet.append(key_of(other))
        if unmet:
            blocked.append((key_of(t), unmet))
        else:
            candidates.append(t)

    state = {
        "project": ident,
        "project_name": project.get("name"),
        "project_id": pid,
        "workspace": WORKSPACE,
        "counts": {
            "epics": len(epics),
            "tasks": len(tasks),
            "todo": len(todo),
            "in_progress": len(wip),
            "done": len(done),
            "cancelled": len(cancelled),
        },
        "in_flight": [key_of(t) for t in wip],
        "waiting_on_human": [{"key": key_of(t), "name": t["name"]} for t in waiting],
        "blocked": [{"key": k, "blocked_by": b} for k, b in blocked],
        "next_task": key_of(candidates[0]) if candidates else None,
        "next_task_name": candidates[0]["name"] if candidates else None,
        "next_task_kind": kind_of(candidates[0]) if candidates else None,
        "queue": [
            {"key": key_of(t), "name": t["name"], "kind": kind_of(t)}
            for t in candidates[: args.queue]
        ],
        "run_limit": args.limit,
    }

    if args.as_json:
        print(json.dumps(state, indent=1))
        return

    print(f"{ident}  {project.get('name')}   (workspace {WORKSPACE})")
    if not args.epic:
        print(f"{'EPIC':<9} {'TODO':>4} {'WIP':>4} {'DONE':>5}  NAME")
        for e in sorted(epics, key=lambda x: x["sequence_id"]):
            kids = [t for t in tasks if t["parent"] == e["id"]]
            k_todo = sum(1 for t in kids if group_of(t) in NOT_STARTED)
            k_wip = sum(1 for t in kids if group_of(t) in IN_FLIGHT)
            k_done = sum(1 for t in kids if group_of(t) in FINISHED)
            print(f"{key_of(e):<9} {k_todo:>4} {k_wip:>4} {k_done:>5}  {e['name'][:46]}")
        print()

    c = state["counts"]
    print(f"tasks             : {c['tasks']}  (todo {c['todo']}, wip {c['in_progress']}, "
          f"done {c['done']}, cancelled {c['cancelled']}, waiting {len(waiting)})")
    for w in state["waiting_on_human"]:
        print(f"!! WAITING ON HUMAN {w['key']}  {w['name'][:44]}")
    if state["waiting_on_human"]:
        print("   -> the run must STOP on these; get the answer, then clear the label")
    if state["in_flight"]:
        print(f"!! IN FLIGHT (finish or reset before starting new): {', '.join(state['in_flight'])}")
    for b in state["blocked"]:
        print(f"!! BLOCKED {b['key']} by {', '.join(b['blocked_by'])}")
    print(f"next task         : {state['next_task'] or '(none actionable)'}"
          + (f"  {state['next_task_name'][:44]}" if state["next_task_name"] else ""))
    if state["next_task_kind"]:
        print(f"  -> kind         : {state['next_task_kind']}"
              + ("  (document-task prompt)" if state["next_task_kind"] == "document"
                 else "  (code-task prompt)"))
    print(f"run limit         : {args.limit} tasks max per run")
    if len(state["queue"]) > 1:
        print("queue             : " + " | ".join(
            f"{q['key']}({q['kind'][:3]})" for q in state["queue"][1:]))


# ------------------------------------------------------------------- show ----
def cmd_show(args):
    item = fetch_by_key(args.key)
    print(f"{args.key.upper()}  {item['name']}")
    print(f"id       : {item['id']}")
    print(f"parent   : {item.get('parent') or '(none)'}")
    print(f"priority : {item.get('priority')}")
    if args.body:
        html = item.get("description_html") or ""
        text = re.sub(r"<li>", "\n  - ", html)
        text = re.sub(r"</(p|h1|h2|h3|ol|ul)>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("&quot;", '"').replace("&amp;", "&")
        text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
        print()
        print(re.sub(r"\n{3,}", "\n\n", text).strip())


# ------------------------------------------------------------ update-plan ----
PLAN_HEADING = "implementation plan"
HEADING_RE = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1\s*>", re.IGNORECASE | re.DOTALL)
LIST_ITEM_RE = re.compile(r"^\s*(?:([-*])|\d+[.)])\s+(.*)$")


def heading_text(inner_html):
    """Normalised heading text: tags stripped, leading numbering and trailing colon dropped."""
    text = html.unescape(re.sub(r"<[^>]+>", "", inner_html))
    return re.sub(r"^[\d.\s]+", "", text).strip().rstrip(":").strip().lower()


def find_plan_section(body_html, key):
    """Offsets (start, end) of the content under the Implementation Plan heading.

    The section runs from the end of that heading to the next heading of the same
    or a higher level, or to the end of the body. Anything else in the body is
    outside the span, so splicing into it cannot touch Description or Acceptance
    Criteria. Exits loudly if the heading is missing or ambiguous.
    """
    headings = list(HEADING_RE.finditer(body_html))
    texts = [heading_text(h.group(2)) for h in headings]
    matches = [h for h, t in zip(headings, texts) if t == PLAN_HEADING]
    if not matches:
        found = ", ".join(repr(t) for t in texts) or "(no headings)"
        sys.exit(f"{key.upper()} has no 'Implementation Plan' heading, so nothing was "
                 f"written. Headings found: {found}")
    if len(matches) > 1:
        sys.exit(f"{key.upper()} has {len(matches)} 'Implementation Plan' headings; "
                 f"refusing to guess which to replace.")
    heading = matches[0]
    level = int(heading.group(1))
    end = next((h.start() for h in headings
                if h.start() > heading.start() and int(h.group(1)) <= level), len(body_html))
    return heading.end(), end


def inline_markup(text):
    text = html.escape(text, quote=False)
    # One pass so `**x**` inside backticks stays literal code instead of nesting <strong>.
    return re.sub(
        r"`([^`]+)`|\*\*([^*]+)\*\*",
        lambda m: f"<code>{m.group(1)}</code>" if m.group(1) is not None
        else f"<strong>{m.group(2)}</strong>",
        text,
    )


def markdown_to_html(text):
    """Small markdown subset: paragraphs, flat -/1. lists, fenced code, `code`, **bold**.

    Headings are rejected: a heading inside the plan would split the section and
    make the next update-plan replace only part of it.
    """
    out, paragraph, items, list_tag, code = [], [], [], None, None

    def flush_paragraph():
        if paragraph:
            out.append(f"<p>{inline_markup(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_list():
        if items:
            body = "".join(f"<li><p>{inline_markup(i)}</p></li>" for i in items)
            out.append(f"<{list_tag}>{body}</{list_tag}>")
            items.clear()

    for line in text.splitlines():
        if line.strip().startswith("```"):
            if code is None:
                flush_paragraph()
                flush_list()
                code = []
            else:
                out.append(f"<pre><code>{html.escape(chr(10).join(code), quote=False)}</code></pre>")
                code = None
        elif code is not None:
            code.append(line)
        elif re.match(r"^\s{0,3}#{1,6}\s", line):
            sys.exit(f"Plan contains a markdown heading ({line.strip()!r}); use bold lead-ins "
                     f"or list items instead, headings would split the section")
        elif not line.strip():
            flush_paragraph()
            flush_list()
        elif (item := LIST_ITEM_RE.match(line)):
            flush_paragraph()
            tag = "ul" if item.group(1) else "ol"
            if items and tag != list_tag:
                flush_list()
            list_tag = tag
            items.append(item.group(2))
        elif items and line[0].isspace():
            items[-1] += " " + line.strip()  # continuation of the previous item
        else:
            flush_list()
            paragraph.append(line.strip())
    if code is not None:
        sys.exit("Plan has an unterminated ``` code fence")
    flush_paragraph()
    flush_list()
    return "".join(out)


def read_plan_html(path):
    """Plan file -> HTML. A file starting with '<' is taken as HTML, else markdown."""
    if not os.path.isfile(path):
        sys.exit(f"Plan file not found: {path}")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if not text.strip():
        sys.exit(f"Plan file {path} is empty; refusing to blank the Implementation Plan")
    if not text.lstrip().startswith("<"):
        return markdown_to_html(text)
    heading = HEADING_RE.search(text)
    if heading:
        sys.exit(f"Plan HTML contains a heading (<h{heading.group(1)}>); use <p><strong> "
                 "lead-ins or lists instead, headings would split the section")
    return text.strip()


def cmd_update_plan(args):
    """PATCH description_html with only the Implementation Plan section replaced."""
    plan_html = read_plan_html(args.file)
    item = fetch_by_key(args.key)
    project = resolve_project(args.key.split("-")[0])
    body_html = item.get("description_html") or ""
    start, end = find_plan_section(body_html, args.key)

    api(
        f"/workspaces/{WORKSPACE}/projects/{project['id']}/work-items/{item['id']}/",
        method="PATCH",
        payload={"description_html": f"{body_html[:start]}{plan_html}{body_html[end:]}"},
    )
    print(f"{args.key.upper()} Implementation Plan replaced "
          f"({end - start} -> {len(plan_html)} chars); rest of the body untouched")


# ------------------------------------------------------------------- move ----
def cmd_move(args):
    item = fetch_by_key(args.key)
    project = resolve_project(args.key.split("-")[0])
    target = resolve_state(project["id"], args.state)

    payload = {"state": target["id"]}
    if args.assign:
        payload["assignees"] = [resolve_member(args.assign)["id"]]

    api(
        f"/workspaces/{WORKSPACE}/projects/{project['id']}/work-items/{item['id']}/",
        method="PATCH",
        payload=payload,
    )
    who = f", assigned {args.assign}" if args.assign else ""
    print(f"{args.key.upper()} -> {target['name']}{who}")


def cmd_wait(args):
    """Flag or clear 'this needs a person'.

    PATCH replaces the whole label list, so the current labels are read first and
    merged — otherwise flagging a task would silently strip its `doc` label and
    change which implementer prompt it routes to on the next run.
    """
    item = fetch_by_key(args.key)
    project = resolve_project(args.key.split("-")[0])
    pid = project["id"]

    labels = {l["name"]: l["id"] for l in paginate(f"/workspaces/{WORKSPACE}/projects/{pid}/labels/")}
    current = set(item.get("labels") or [])

    if args.clear:
        target = labels.get(WAITING_LABEL)
        if not target or target not in current:
            print(f"{args.key.upper()} was not flagged; nothing to clear")
            return
        current.discard(target)
        verb = "cleared"
    else:
        target = labels.get(WAITING_LABEL)
        if not target:
            status, made = call_label(pid, WAITING_LABEL)
            target = made["id"]
        if target in current:
            print(f"{args.key.upper()} already flagged as {WAITING_LABEL}")
            return
        current.add(target)
        verb = "flagged"

    api(
        f"/workspaces/{WORKSPACE}/projects/{pid}/work-items/{item['id']}/",
        method="PATCH",
        payload={"labels": sorted(current)},
    )
    who = f" — needs {args.who}" if args.who else ""
    print(f"{args.key.upper()} {verb} {WAITING_LABEL}{who}")


def call_label(project_id, name):
    body = api(
        f"/workspaces/{WORKSPACE}/projects/{project_id}/labels/",
        method="POST",
        payload={"name": name, "color": "#F59E0B"},
    )
    return 201, body


def main():
    ap = argparse.ArgumentParser(description="Plane state helper for plane-task-workflow")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("state", help="roll-up table and next task")
    s.add_argument("project", help="project identifier, e.g. READ")
    s.add_argument("--epic", help="restrict to tasks under one epic, e.g. READ-14")
    s.add_argument("--limit", type=int, default=10, help="tasks per run (default 10)")
    s.add_argument("--probe", type=int, default=3,
                   help="how many queued tasks to check for blockers (one API call each; "
                        "the key is rate-limited, so keep this small)")
    s.add_argument("--queue", type=int, default=4, help="how many upcoming keys to preview")
    s.add_argument("--json", action="store_true", dest="as_json")
    s.set_defaults(func=cmd_state)

    h = sub.add_parser("show", help="one work item")
    h.add_argument("key", help="e.g. READ-16")
    h.add_argument("--no-body", dest="body", action="store_false", default=True)
    h.set_defaults(func=cmd_show)

    u = sub.add_parser("update-plan",
                       help="replace only the Implementation Plan section of a work item body")
    u.add_argument("key", help="e.g. READ-16")
    u.add_argument("--file", required=True,
                   help="markdown (or HTML) file holding the new plan, without its heading")
    u.set_defaults(func=cmd_update_plan)

    w = sub.add_parser("wait", help=f"flag/clear '{WAITING_LABEL}' on a work item")
    w.add_argument("key")
    w.add_argument("--who", help="who is needed, e.g. 'ops lead' (shown in output)")
    w.add_argument("--clear", action="store_true", help="remove the flag instead of setting it")
    w.set_defaults(func=cmd_wait)

    m = sub.add_parser("move", help="transition a work item")
    m.add_argument("key")
    m.add_argument("state", help="state name, e.g. 'In Progress', or a group name")
    m.add_argument("--assign", help="substring of a member display name or email")
    m.set_defaults(func=cmd_move)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
