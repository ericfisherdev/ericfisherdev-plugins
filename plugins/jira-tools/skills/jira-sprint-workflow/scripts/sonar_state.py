#!/usr/bin/env python3
"""Compact SonarQube/SonarCloud state for the jira-sprint-workflow skill's --sq mode.

Same purpose as sprint_state.py: collapse a pile of API JSON into a few lines so the
orchestrator can decide without loading payloads into context.

Usage:
  sonar_state.py key <REPO_PATH>                               # is this repo analysed?
  sonar_state.py gate <PROJECT_KEY> [--pr N] [--branch NAME]   # quality gate verdict
  sonar_state.py hotspots <PROJECT_KEY> [--pr N]               # TO_REVIEW hotspots
  sonar_state.py issues <PROJECT_KEY> [--pr N] [--branch NAME] # open issues
  ... [--json]

`key` is the entry point: it reads sonar-project.properties out of the repo and
exits 0 with the project key when the repo is analysed, 1 when it is not. That
exit status is how callers decide whether to run Sonar steps at all, so no flag
has to be remembered. It needs no credentials; the other commands do.

Environment: SONARQUBE_URL, SONARQUBE_TOKEN (Bearer auth; SonarCloud or self-hosted)
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def api(path, params):
    base = os.environ.get("SONARQUBE_URL", "").rstrip("/")
    token = os.environ.get("SONARQUBE_TOKEN", "")
    if not base or not token:
        sys.exit("SONARQUBE_URL and SONARQUBE_TOKEN must be set to use --sq mode.")
    url = f"{base}{path}?{urllib.parse.urlencode({k: v for k, v in params.items() if v})}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        sys.exit(f"Sonar API {exc.code} on {path}: {exc.read()[:200].decode(errors='replace')}")


def cmd_key(args):
    """Resolve a repo's Sonar project key from sonar-project.properties.

    Exit status is the interesting part: 0 means "this repo is analysed by Sonar,
    here is its key", 1 means "it is not". Callers branch on that instead of
    being told about Sonar by a flag.
    """
    root = os.path.abspath(os.path.expanduser(args.repo))
    # Repos here use a bare clone plus worktrees, so the properties file lives in
    # a worktree (main/) rather than at the path the caller thinks of as "the
    # repo". Check the plain layout first, then main/.
    candidates = [
        os.path.join(root, "sonar-project.properties"),
        os.path.join(root, "main", "sonar-project.properties"),
    ]
    path = next((p for p in candidates if os.path.isfile(p)), None)
    if path is None:
        if args.as_json:
            print(json.dumps({"sonar": False, "reason": "no sonar-project.properties"}))
        else:
            print(f"sonar: not configured for {root} (no sonar-project.properties)")
        sys.exit(1)

    props = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip()

    key = props.get("sonar.projectKey")
    if not key:
        # The file exists but names no project. Treat that as misconfiguration
        # worth reporting, not as "Sonar is off" — silently skipping would hide it.
        sys.exit(f"sonar: {path} has no sonar.projectKey")

    out = {"sonar": True, "projectKey": key,
           "organization": props.get("sonar.organization"), "path": path}
    print(json.dumps(out) if args.as_json else key)


def cmd_gate(args):
    data = api("/api/qualitygates/project_status", {
        "projectKey": args.project, "pullRequest": args.pr, "branch": args.branch,
    })
    status = data.get("projectStatus", {})
    conditions = status.get("conditions", [])
    failing = [c for c in conditions if c.get("status") == "ERROR"]
    out = {
        "status": status.get("status"),
        "passed": status.get("status") == "OK",
        "failing": [
            {
                "metric": c.get("metricKey"),
                "actual": c.get("actualValue"),
                "op": c.get("comparator"),
                "threshold": c.get("errorThreshold"),
            }
            for c in failing
        ],
    }
    if args.as_json:
        print(json.dumps(out, indent=1))
        return
    scope = f"PR {args.pr}" if args.pr else (args.branch or "main branch")
    print(f"quality gate [{args.project} · {scope}]: {out['status']}")
    for c in out["failing"]:
        print(f"  FAIL {c['metric']}: {c['actual']} (needs {c['op']} {c['threshold']})")
    if out["passed"]:
        print("  all conditions pass")


def cmd_hotspots(args):
    data = api("/api/hotspots/search", {
        "projectKey": args.project, "status": "TO_REVIEW", "ps": 100, "pullRequest": args.pr,
    })
    hotspots = [
        {
            "key": h.get("key"),
            "probability": h.get("vulnerabilityProbability"),
            "category": h.get("securityCategory"),
            "component": (h.get("component") or "").split(":")[-1],
            "line": h.get("line"),
            "message": h.get("message"),
        }
        for h in data.get("hotspots", [])
    ]
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    hotspots.sort(key=lambda h: (order.get(h["probability"], 9), h["component"] or ""))

    if args.as_json:
        print(json.dumps({"total": len(hotspots), "hotspots": hotspots}, indent=1))
        return
    print(f"hotspots TO_REVIEW [{args.project}]: {len(hotspots)}")
    for h in hotspots:
        print(f"  {h['probability']:<6} {h['category']:<22} "
              f"{h['component']}:{h['line']}  {(h['message'] or '')[:52]}")
    if not hotspots:
        print("  none — security review is clean")


def cmd_issues(args):
    # "componentKeys", not "components": /api/issues/search rejects the latter
    # with a 400 naming the parameters it does accept, and rejects it whether or
    # not pullRequest is supplied — so both the branch and the PR form 400'd.
    # --branch is honoured here too; the subparser has always accepted the flag,
    # and silently ignoring it returned main-branch issues under a branch label.
    data = api("/api/issues/search", {
        "componentKeys": args.project, "pullRequest": args.pr, "branch": args.branch,
        "resolved": "false", "ps": 100,
    })
    issues = [
        {
            # "key" identifies this exact finding and "rule" the check that
            # raised it. Both are needed downstream: rule to group findings that
            # share a fix, key to recognise a finding already filed as a ticket.
            "key": i.get("key"),
            "rule": i.get("rule"),
            "severity": i.get("severity"),
            "type": i.get("type"),
            "component": (i.get("component") or "").split(":")[-1],
            "line": i.get("line"),
            "effort": i.get("effort"),
            "message": i.get("message"),
        }
        for i in data.get("issues", [])
    ]
    order = {"BLOCKER": 0, "CRITICAL": 1, "MAJOR": 2, "MINOR": 3, "INFO": 4}
    issues.sort(key=lambda i: (order.get(i["severity"], 9), i["component"] or "", i["line"] or 0))

    if args.as_json:
        print(json.dumps({"total": len(issues), "issues": issues}, indent=1))
        return
    scope = f"PR {args.pr}" if args.pr else (args.branch or "main branch")
    print(f"open issues [{args.project} · {scope}]: {len(issues)}")
    for i in issues:
        print(f"  {i['severity']:<9} {i['rule']:<14} {i['component']}:{i['line']}  "
              f"{(i['message'] or '')[:50]}")
    if not issues:
        print("  none — no open issues")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("gate", "hotspots", "issues"):
        p = sub.add_parser(name)
        p.add_argument("project")
        p.add_argument("--pr")
        p.add_argument("--branch")
        p.add_argument("--json", action="store_true", dest="as_json")
    # "key" takes a repo path, not a project key, and needs no credentials: it
    # reads the checked-in properties file rather than calling the API.
    pk = sub.add_parser("key")
    pk.add_argument("repo")
    pk.add_argument("--json", action="store_true", dest="as_json")

    args = ap.parse_args()
    {"gate": cmd_gate, "hotspots": cmd_hotspots,
     "issues": cmd_issues, "key": cmd_key}[args.cmd](args)


if __name__ == "__main__":
    main()
