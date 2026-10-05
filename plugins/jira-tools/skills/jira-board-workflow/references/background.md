# Background for jira-board-workflow

Why the gates and rules in SKILL.md exist. Read this when you are changing a gate or when a rule looks arbitrary. None of it is needed to run the workflow.

## Why the workflow is built around subagents

The source workflow says "clear your context after each merge." A session cannot clear
itself — `/clear` is user-invoked only, and no hook can trigger it. Subagents solve the
same problem natively: each starts with a fresh context and returns only a short summary.

## Why Phase 3.6 exists

Per-PR triage (step 10) only ever cleaned up what each PR introduced. What is left is the
pre-existing debt on the default branch: findings that predate the run, plus anything the
per-PR passes deliberately declined to fix. Phase 3.6 turns that residue into tickets so
it is tracked rather than silently carried.

## Why "known flake" needs proof

A flake documented in a repo's CLAUDE.md makes the label the default assumption, which is
what lets a real regression through. Settle it with `job_history.py "<job name>"`: a flake
fails intermittently on the same branch, while a regression fails every run on one branch
while others stay clean, or only after a given timestamp. Failing 4-of-4 on your branch
while siblings pass is not a flake.

## Why `required_status_checks` alone is not enough

A branch can require approving reviews with no required checks, in which case that field
reads null and the PR still cannot merge. `merge_readiness.py <PR>` reads protection and
rulesets together; a brief built on a partial read gets passed into subagent prompts and
costs them a denied merge attempt.

## Why `archivedDate` JQL is a trap

On instances without Jira Premium archiving, both `archivedDate IS EMPTY` and
`archivedDate IS NOT EMPTY` match **zero** issues, and the field is not listed by
`/rest/api/3/field` at all. A queue JQL carrying that clause comes back silently empty.
Archived exclusion is structural instead: `board_state.py` reads from
`/rest/agile/1.0/board/<id>/issue`, which never returns archived issues, plus a defensive
drop of any row that does carry `archivedDate`/`archivedBy`. Never put the clause in
`--jql`.

## Why the worktree branches off `origin/HEAD`

Repo layouts vary: some are a bare repo with a `main/` worktree, some have no local
default-branch checkout at all. Step 3 of the implementer procedure therefore fetches
`origin` and branches off `origin/HEAD`, and step 13 fetches rather than pulling. Branching
off the remote head means each ticket's worktree is fresh and never depends on another
checkout being up to date.

## Why rebutted review threads are resolved

Resolving rebuttals is deliberate and diverges from the `address-pr-reviews` default: the
merge gate (step 12) cannot merge over an unresolved thread, so an unresolved rebuttal
stalls the run. The reply carries the reasoning; the reviewer can reopen the thread if they
disagree, and a reopened thread blocks the merge again.
