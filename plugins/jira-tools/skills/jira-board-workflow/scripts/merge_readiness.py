#!/usr/bin/env python3
"""Can this PR be merged, and if not, exactly what is stopping it?

Written because reading one part of the answer is worse than reading none. Checking
`required_status_checks` alone on a branch whose protection is a *review* rule
returns nulls and looks like "nothing is required" — which is how a green PR ends
up BLOCKED with no failing check to explain it. This reads every gate together:

  * PR state: open, draft, already merged
  * checks on the CURRENT head (a stale green on an older commit is not a pass)
  * review decision, and the approving-review count the branch actually requires
  * unresolved review threads
  * classic branch protection AND rulesets, since either can impose rules

Usage:
  merge_readiness.py <PR> [--repo PATH | --slug OWNER/NAME] [--verbose]

Exit status: 0 mergeable, 1 blocked, 2 could not answer. So:
  merge_readiness.py 217 && gh pr merge 217 --rebase

It never merges anything and never overrides anything; it only reports.
"""

import argparse
import sys

import gh_common as gh

PR_FIELDS = (
    "number,title,state,isDraft,mergeable,mergeStateStatus,reviewDecision,"
    "baseRefName,headRefOid,statusCheckRollup,latestReviews"
)

UNRESOLVED_THREADS = """
query($owner:String!,$repo:String!,$number:Int!){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$number){
      reviewThreads(first:100){ nodes{ isResolved isOutdated } }
    }
  }
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pr", type=int, help="pull request number")
    parser.add_argument(
        "--verbose", action="store_true", help="also list the passing checks"
    )
    gh.add_repo_args(parser)
    args = parser.parse_args()

    slug = gh.resolve_slug(args.slug, args.repo)
    pr = gh.gh(["pr", "view", str(args.pr), "-R", slug, "--json", PR_FIELDS])

    checks = _classify_checks(pr.get("statusCheckRollup") or [])
    protection = _protection(slug, pr["baseRefName"])
    unresolved = _unresolved_threads(slug, args.pr)

    _print_summary(pr, checks, protection, unresolved, args.verbose)

    if pr["state"] == "MERGED":
        print("\nVERDICT: already merged")
        return 0

    blockers = _blockers(pr, checks, protection, unresolved)
    print()
    if blockers:
        print(f"VERDICT: BLOCKED — {len(blockers)} reason(s)")
        for blocker in blockers:
            print(f"  - {blocker}")
        return 1
    print("VERDICT: MERGEABLE — every gate satisfied on the current head")
    return 0


def _classify_checks(rollup):
    """Split the head's checks into failing / pending / passing.

    statusCheckRollup mixes CheckRun (conclusion) and StatusContext (state) shapes,
    so normalise before judging.
    """
    failing, pending, passing = [], [], []
    for check in rollup:
        name = check.get("name") or check.get("context") or "?"
        verdict = (check.get("conclusion") or check.get("state") or "").upper()
        if verdict in ("SUCCESS", "NEUTRAL", "SKIPPED"):
            passing.append(name)
        elif verdict in ("", "PENDING", "IN_PROGRESS", "QUEUED", "EXPECTED"):
            pending.append(name)
        else:
            failing.append(f"{name} ({verdict.lower()})")
    return {"failing": failing, "pending": pending, "passing": passing}


def _protection(slug, base):
    """Merge classic branch protection with any ruleset rules into one shape.

    Both mechanisms can require reviews or checks, and a repo can use either, so
    reading one alone is how this check gets a wrong answer.
    """
    owner, repo = slug.split("/", 1)
    result = {"required_reviews": 0, "required_checks": [], "enforce_admins": False,
              "source": "none"}

    classic = gh.gh_api(
        f"repos/{owner}/{repo}/branches/{base}/protection", allow_failure=True
    )
    if classic:
        result["source"] = "branch protection"
        reviews = classic.get("required_pull_request_reviews") or {}
        result["required_reviews"] = reviews.get("required_approving_review_count", 0) or 0
        status = classic.get("required_status_checks") or {}
        result["required_checks"] = [
            c["context"] if isinstance(c, dict) else c
            for c in (status.get("checks") or status.get("contexts") or [])
        ]
        result["enforce_admins"] = bool((classic.get("enforce_admins") or {}).get("enabled"))

    rules = gh.gh_api(
        f"repos/{owner}/{repo}/rules/branches/{base}", allow_failure=True
    ) or []
    for rule in rules:
        params = rule.get("parameters") or {}
        if rule.get("type") == "pull_request":
            count = params.get("required_approving_review_count", 0) or 0
            if count > result["required_reviews"]:
                result["required_reviews"] = count
                result["source"] = "ruleset"
        elif rule.get("type") == "required_status_checks":
            names = [
                c.get("context")
                for c in params.get("required_status_checks", [])
                if c.get("context")
            ]
            result["required_checks"] = sorted(set(result["required_checks"]) | set(names))
            if names and result["source"] == "none":
                result["source"] = "ruleset"
    return result


def _unresolved_threads(slug, number):
    owner, repo = slug.split("/", 1)
    data = gh.graphql(
        UNRESOLVED_THREADS, {"owner": owner, "repo": repo, "number": number}
    )
    nodes = (
        data.get("data", {})
        .get("repository", {})
        .get("pullRequest", {})
        .get("reviewThreads", {})
        .get("nodes", [])
    )
    return [n for n in nodes if not n.get("isResolved")]


def _blockers(pr, checks, protection, unresolved):
    """Every reason the merge would be refused, in the order a human would hit them."""
    blockers = []
    if pr["state"] != "OPEN":
        blockers.append(f"PR state is {pr['state']}")
    if pr["isDraft"]:
        blockers.append("PR is a draft — gh pr ready first")
    if checks["failing"]:
        blockers.append(f"failing checks: {', '.join(checks['failing'])}")
    if checks["pending"]:
        blockers.append(f"checks still running: {', '.join(checks['pending'])}")
    if protection["required_reviews"] and pr.get("reviewDecision") != "APPROVED":
        blockers.append(
            f"needs {protection['required_reviews']} approving review(s) "
            f"[{protection['source']}]; current decision: "
            f"{pr.get('reviewDecision') or 'none'}"
        )
    if unresolved:
        blockers.append(f"{len(unresolved)} unresolved review thread(s)")
    missing = set(protection["required_checks"]) - set(
        checks["passing"] + checks["failing"] + checks["pending"]
    )
    if missing:
        blockers.append(f"required check(s) never reported: {', '.join(sorted(missing))}")
    return blockers


def _print_summary(pr, checks, protection, unresolved, verbose):
    print(f"PR #{pr['number']}  {pr['title'][:70]}")
    print(f"  state         : {pr['state']}{' (draft)' if pr['isDraft'] else ''}")
    print(f"  head          : {pr['headRefOid'][:9]} -> {pr['baseRefName']}")
    print(f"  mergeState    : {pr.get('mergeStateStatus')}  mergeable={pr.get('mergeable')}")
    print(f"  reviewDecision: {pr.get('reviewDecision') or 'none'}")
    print(
        f"  checks        : {len(checks['passing'])} pass, "
        f"{len(checks['failing'])} fail, {len(checks['pending'])} pending"
    )
    if checks["failing"]:
        print(f"    failing: {', '.join(checks['failing'])}")
    if verbose and checks["passing"]:
        print(f"    passing: {', '.join(checks['passing'])}")
    print(f"  threads       : {len(unresolved)} unresolved")
    print(
        f"  protection    : {protection['source']}, "
        f"{protection['required_reviews']} review(s) required, "
        f"{len(protection['required_checks'])} required check(s), "
        f"enforce_admins={protection['enforce_admins']}"
    )


if __name__ == "__main__":
    sys.exit(main())
