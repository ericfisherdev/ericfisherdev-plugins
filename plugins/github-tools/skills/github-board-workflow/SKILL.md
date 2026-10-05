---
name: github-board-workflow
description: Run a GitHub Projects queue end to end — dependency audit, per-issue implementation planning with points, then sequential implement/review/merge — delegating every issue to a fresh subagent so the main context never accumulates. Use for repos tracked on a GitHub Projects board (not Jira), or when the user asks to "work the board", "run these issues", "work this parent issue", "work the ai-convobot project", or to take a set of GitHub issues from Todo through Done.
argument-hint: '<OWNER/REPO> --project <N> [--parent <ISSUE>|--label <L>|--workstream <W>|--issues <a,b>|--search "..."] [--repo <path>] [--no-sq] [--plan-only|--work-only]'
---

# GitHub Board Workflow

## Contents

- Needs
- Overview
- Rules that hold every time
- Jira sibling and GitHub equivalents
- Invocation
- Why it is built this way
- The one script
- Phase 0 — Preflight
- Phase 1 — Dependency audit
- Phase 2 — Planning (parallel, Fable)
- Phase 3 — Implementation (sequential, Sonnet)
  - Handling `awaiting-review`
  - Parent issues (the PR-per-parent pattern)
- Phase 3.5 / 3.6 — Sonar (Sonar repos only)
- Phase 4 — Report
- Orchestrator context rules
- Standing authorizations
- Known gotchas
- Reference

## Needs

- `gh` — GitHub CLI, logged in with the `project` scope (`pacman -S github-cli`, then `gh auth login`)
- python3 (3.8+)
- [scripts/gh_board.py](scripts/gh_board.py) — board `state` / `set` / `add` helper (the one script)
- [scripts/ci_failure.py](scripts/ci_failure.py) — names the failing job, step and decisive log lines for a PR
- [scripts/job_history.py](scripts/job_history.py) — proves or disproves a "known flake" claim from a job's run history
- [scripts/merge_readiness.py](scripts/merge_readiness.py) — one-line merge verdict for a PR
- [scripts/gh_common.py](scripts/gh_common.py) — shared helpers imported by the three CI scripts above
- `board-planner` and `board-implementer` agent definitions in `~/.claude/agents/` — the phase agents below run through them; they are not bundled with this plugin
- jira-tools plugin (optional, only for the Sonar check in Phase 0) — provides `skills/jira-sprint-workflow/scripts/sonar_state.py`

## Overview

Drives a queue of GitHub issues from planning to merged. The orchestrator (you, in the
main session) never writes code, never reads a diff, and never reads a full issue body.
Every issue is handled by a **subagent with its own context window**, which is what keeps
a 20-issue run from filling a 200k-token session.

## Rules that hold every time

- `state` is **the only way you read board state**; never page through project JSON or
  `gh issue list` output yourself.
- **Never** read issue bodies, source files, diffs, PR bodies, or CI logs in the main
  session. Subagents do that.
- Your working memory is the ledger: one line per issue.
- Cap every subagent's return at ~6 lines and say so in the prompt.
- Never use an admin override to merge. If a merge is refused (required review, protected
  branch), STOP and report.

## Jira sibling and GitHub equivalents

This is the GitHub sibling of `jira-board-workflow`. Same phases, same subagent contract,
same merge gates. What differs is where state lives:

| Jira concept | GitHub equivalent here |
|---|---|
| Project key + board | `OWNER/REPO` + a GitHub Projects (v2) board, by number |
| Status `To Do → Plan Created → In Progress → In Review → Done` | The board's `Status` single-select field with those five options (`Todo` spelled without a space) |
| Story points `customfield_10016` | Board NUMBER field named `Points` |
| Epic and its children | A parent issue and its **sub-issues** |
| "is blocked by" link | GitHub **issue dependency** (`blocked by`) |
| Assignee "Eric Fisher" | GitHub login `ericfisherdev` |
| Label | Label, plus an optional `Workstream` single-select field on the board |
| Jira key in PR title | `(#N)` in the PR title, and `Closes #N` in the PR body |

A board must carry the five Status options and a `Points` number field before a run.
The `ai-convobot` board (`https://github.com/users/ericfisherdev/projects/2`) already
does. For a new board, add them once in the project settings UI, or via
`updateProjectV2Field` — note that rewriting Status options **regenerates option ids and
blanks every item's Status**, so do it before items exist or re-set them afterwards.

## Invocation

```
/github-board-workflow <OWNER/REPO> --project <N>
        [--parent <ISSUE>|--label <L>|--workstream <W>|--issues <a,b>|--search "..."]
        [--repo <path>] [--no-sq] [--plan-only|--work-only]
```

- `OWNER/REPO` — e.g. `ericfisherdev/ai-convobot`
- `--project` — board number (user project `N` under the repo owner; pass
  `--project-owner` to the script if the board belongs to someone else)
- **scope** — `--parent`, `--label`, `--workstream`, `--issues`, or `--search`. A board has
  no natural size the way a sprint does, so an unscoped board with more than 12 open
  workable issues is **refused**; see Phase 0.
- `--repo` — local checkout path; default is the current working directory
- `--no-sq` — force SonarQube steps off (normally auto-detected; see the Jira skill)
- `--plan-only` — stop after planning · `--work-only` — assume planning is done

## Why it is built this way

A session cannot clear itself; subagents start fresh and return only a short summary.
Model **and effort** are fixed per phase through two agent definitions in
`~/.claude/agents/`, so a run never depends on the session's `/effort` setting:

| Phase | `subagent_type` | Model | Effort | Why |
|---|---|---|---|---|
| Planning | `board-planner` | `fable` (pass `model: "fable"` on the Agent call) | `medium` (frontmatter) | Research + plan writing, one agent per issue, in parallel |
| Implementation | `board-implementer` | `sonnet` (frontmatter) | `high` (frontmatter) | Code, CI, review handling, merge — one agent per issue, strictly sequential |
| Security triage (Sonar repos) | `general-purpose` | `opus` | session | Judging real risk vs. false positive |
| Orchestration | you | inherit | session | You only route and report |

`board-planner` declares `model: inherit` because `fable` is not a documented frontmatter
alias; the Agent call's `model` override is documented to take precedence, so **always
pass `model: "fable"` when spawning it**. `board-implementer` declares `model: sonnet`
and `effort: high` in its frontmatter; do not override either on the call. Never spawn
a planner or implementer as a bare `general-purpose` agent, because that drops the
effort setting.

## The one script

```sh
S="${CLAUDE_SKILL_DIR}/scripts/gh_board.py"
python3 $S state OWNER/REPO --project N [scope flags] [--include-parents] [--json]
python3 $S set   OWNER/REPO --project N ISSUE [--status S] [--points P] [--assignee LOGIN]
python3 $S add   OWNER/REPO --project N ISSUE
```

Read board state only through `state` (see [Rules that hold every time](#rules-that-hold-every-time)).
It prints one table plus a verdict: `planning complete`,
external blockers, in-flight issues, unassigned issues, and `next issue`.

`set` is how every subagent advances an issue. It resolves item ids and option ids
internally, sets the assignee **before** the status so a transition never lands
unassigned, and on `--status Done` also closes the issue. It auto-adds the issue to the
board if it is not yet an item.

Issues that have sub-issues are containers and are dropped from the queue unless
`--include-parents` is passed. Closed issues and `Done` items are always excluded.

## Phase 0 — Preflight

```sh
python3 $S state OWNER/REPO --project N [scope flags]
```

**If the guardrail trips** (open count exceeds `--max-queue`, no scope given), **stop and
ask the user which issues this run covers**. Do not invent a scope and do not raise
`--max-queue` on your own.

Confirm:
- `gh auth status` is logged in **with the `project` scope** — `gh project` commands fail
  without it. If missing, see Known gotchas for how to refresh on this machine.
- `--repo` path exists and `git -C <path> remote get-url origin` points at `OWNER/REPO`.

Resolve Sonar once, here, exactly as `jira-board-workflow` does (it reuses
`sonar_state.py key <REPO_PATH>` from the jira-tools plugin's `jira-sprint-workflow` skill), and
carry the answer through the run. exit 0 = ON, exit 1 = OFF, anything else = stop.

## Phase 1 — Dependency audit

From the Phase 0 table:

1. **External blockers** listed (an open blocker not in this queue) → **stop and report**.
   The user widens the scope or defers the issue. A parent issue that blocks a sibling
   parent (e.g. `#57 blocked by #56`) shows up here when you scope by workstream; scope
   by `--parent` instead, or run the blocking parent's children first.
2. Issues **in flight** (`In Progress` / `In Review`) from a previous run → report and ask
   whether to resume or reset.
3. Note the **blocked-by column**. `next issue` already respects it.
4. Otherwise continue.

## Phase 2 — Planning (parallel, Fable)

Skip if `planning complete : True` or `--work-only`.

Spawn **one `board-planner` subagent per `Todo` issue, all in parallel**, each with
`subagent_type: "board-planner"` and `model: "fable"`. Each gets the queue list
(numbers + titles only). The agent file already carries the rules below; the prompt
restates the specifics so the planner has them without reading the skill.

Planner prompt template. Send verbatim, filling <placeholders>.

```
Plan GitHub issue #<N> in <OWNER/REPO>. Do not write any implementation code.

Repository checkout: <REPO_PATH>
Board: project <PROJECT_NUMBER>
Other issues in this queue (for cross-impact analysis only):
<#N: title list>

Steps:
1. Read the issue: gh issue view <N> -R <OWNER/REPO> --comments
2. Research every technology the issue touches using context7 (resolve-library-id then
   query-docs). Prefer context7 over web search. Never guess an API — verify it.
3. Read the actual code the issue will touch. Match existing patterns and conventions.
   Read the repo's CLAUDE.md and, if present, .claude/CODEMAP.md first.
4. Judge whether this issue forces changes to any sibling issue above. Say so explicitly.
5. Rewrite the issue's "## Implementation Plan" section with a concrete, file-level plan.
   Keep the existing "## Description" and "## Acceptance Criteria" unless now wrong.
   Write the full new body to a temp file and apply it:
     gh issue edit <N> -R <OWNER/REPO> --body-file <tmp>
6. Estimate points (Fibonacci: 1,2,3,5,8,13). 8+ means it should be split — say so.
7. Advance the issue in ONE call — points, assignee, and status together, so it never
   leaves Todo unassigned:
     python3 ${CLAUDE_SKILL_DIR}/scripts/gh_board.py set \
       <OWNER/REPO> --project <PROJECT_NUMBER> <N> \
       --points <P> --assignee ericfisherdev --status "Plan Created"

Return AT MOST 6 lines: #N, points, one-line plan summary, and any cross-issue impact
you found. Do not return the plan body — it is already on the issue.
```

After the fan-out, re-run `state` with the same scope. **Every issue must be
`Plan Created`, pointed, and assigned before Phase 3.** Fix any `!! UNASSIGNED` with
`gh_board.py set ... --assignee ericfisherdev`. Raise cross-issue impacts with the user.

Stop here if `--plan-only`.

## Phase 3 — Implementation (sequential, Sonnet)

Loop until `next issue` is `(none actionable)`. **One issue at a time**; the next starts
only after the previous is merged and `origin` refetched.

Each iteration:
1. `state` with the run's scope → `next issue`.
2. Spawn **one `board-implementer` subagent** (`subagent_type: "board-implementer"`,
   no model override) with the prompt below.
3. Ledger line: `#N | PR # | merged|awaiting-review|blocked|failed`.
4. Move on. **Do not read the diff, the PR body, or the issue.**

### Handling `awaiting-review`

Identical to `jira-board-workflow`: you own the watch. Poll on a long interval (~10 min,
a delay of about 600 seconds, using `ScheduleWakeup`; if that tool is not available, use
`/loop` at the same interval; never a tight loop) with
`python "${CLAUDE_SKILL_DIR}/scripts/merge_readiness.py" <PR> --repo <REPO_PATH>`
(one verdict line: mergeable, or exactly what blocks it), never read review bodies, and spawn a fresh
`board-implementer` subagent to resume at step 11 (new review activity) or step 13
(merged). After ~2 hours
of silence, ask the user whether to merge under the standing authorization.

Implementer prompt template. Send verbatim, filling <placeholders>.

```
Implement GitHub issue #<N> end to end, in <OWNER/REPO>, checkout <REPO_PATH>, board
project <PROJECT_NUMBER>.

Board helper (use it for every status change; never edit project fields by hand):
  BOARD="python3 ${CLAUDE_SKILL_DIR}/scripts/gh_board.py"

Copy this checklist and track progress:
- [ ] Step 1: Mark the issue In Progress
- [ ] Step 2: Read the Implementation Plan
- [ ] Step 3: Create a worktree off the fetched remote head
- [ ] Step 4: Implement, test, and run the repo's gates
- [ ] Step 5: Stage changes
- [ ] Step 6: Commit
- [ ] Step 7: Push and open a draft PR, mark In Review
- [ ] Step 8: Wait for CI to pass
- [ ] Step 9: Take the PR out of draft
- [ ] Step 10: Sonar triage (Sonar repos only)
- [ ] Step 11: Review watch
- [ ] Step 12: Merge gate and merge
- [ ] Step 13: Refetch origin
- [ ] Step 14: Mark Done and remove the worktree

1. $BOARD set <OWNER/REPO> --project <PROJECT_NUMBER> <N> --status "In Progress"
2. Read the issue's Implementation Plan (gh issue view <N> -R <OWNER/REPO>) and follow it.
3. Create a worktree off the freshly fetched remote head. Do NOT assume a local main
   checkout exists:
     git -C <REPO_PATH> fetch origin
     BASE=$(git -C <REPO_PATH> symbolic-ref --short refs/remotes/origin/HEAD)  # origin/main
     git -C <REPO_PATH> worktree add ../wt-<N> -b <type>/<N>-<short-slug> "$BASE"
4. Implement. Match surrounding code. Write tests. Run the repo's own gates (make check,
   or whatever CLAUDE.md names) until green. If the repo has no Makefile yet, run the
   individual commands CLAUDE.md lists.
5. git add -A
6. Commit with Conventional Commits. Lowercase subject, no trailing period, names the
   specific thing that changed. Never "address review findings".
7. Push and open a DRAFT PR against <OWNER/REPO>, base = default branch. Title:
     <type>: <lowercase description> (#<N>)
   For example: "fix: revalidate fast-drive checkpoint copy against source before
   serving (#166)".
   Body must contain a line `Closes #<N>` so the merge closes the issue. Check recent PR
   titles (gh pr list -R <OWNER/REPO> --state all --limit 20 --json title) and match
   what is actually there.
   Then: $BOARD set <OWNER/REPO> --project <PROJECT_NUMBER> <N> --status "In Review"
8. Wait for CI (gh pr checks <PR> --watch). Fix failures and push until every check
   passes. If the repo has no CI workflow enabled, say so in your return and treat the
   local gates from step 4 as the bar.
   To see WHY a run is red, do not page through logs — this prints the failing job, the
   failing step and the few decisive log lines, and exits 0 green / 1 failing:
     python "${CLAUDE_SKILL_DIR}/scripts/ci_failure.py" --pr <PR> --repo <REPO_PATH>
   Before writing any failure off as a known flake, prove it:
     python "${CLAUDE_SKILL_DIR}/scripts/job_history.py" "<job name>" --repo <REPO_PATH>
9. Take the PR out of draft: gh pr ready <PR>
10. [Sonar repos only] /sonar-triage <SONAR_KEY> --pr <PR> --repo <REPO_PATH>, scoped to
    findings this PR added. Wait for analysis; a fix re-runs CI, go back to step 8.
11. REVIEW WATCH: watch until merged. Each cycle read
      python "${CLAUDE_SKILL_DIR}/scripts/merge_readiness.py" <PR> --repo <REPO_PATH>
    which reports PR state, the checks on the current head, the review decision, the
    unresolved-thread count and the branch's actual protection rules in one pass.
    a. MERGED → step 13.
    b. CHANGES_REQUESTED or any unresolved actionable thread → address with the
       address-pr-reviews skill, then the reply-and-resolve procedure below. Commit under
       step 6 rules, push, wait for green (step 8), re-run step 10 on a Sonar repo.
    c. APPROVED, zero unresolved threads, CI green on current head → step 12.
    d. No activity → wait via Monitor / gh pr checks --watch, never busy-poll. Do NOT
       end your turn to wait for a notification — none is coming, and the run stalls
       until the orchestrator nudges you. Waiting happens inside a turn, with a blocking
       watch. After ~30 min of no reviewer activity, return `awaiting-review` plus the
       PR number.
    If the repo has no reviewers configured and no bot reviews within one cycle, rule c
    applies once CI is green: the standing authorization covers merging a clean PR.
12. MERGE GATE: confirm it mechanically first — one command covers the whole gate and
    exits 1 with the specific blockers if it is not satisfied:
      python "${CLAUDE_SKILL_DIR}/scripts/merge_readiness.py" <PR> --repo <REPO_PATH>
    Every required check green on the PR's CURRENT head AND zero unresolved threads,
    then: gh pr merge <PR> --rebase --delete-branch
    If a required check fails and you cannot fix it, stop and report. If the merge is
    refused for another reason, STOP and report; the no-admin-override rule under "Rules
    that hold every time" applies.
13. git -C <REPO_PATH> fetch origin --prune
14. $BOARD set <OWNER/REPO> --project <PROJECT_NUMBER> <N> --assignee ericfisherdev --status Done
    (closes the issue if the PR's `Closes #N` did not already). Then remove the worktree:
      git -C <REPO_PATH> worktree remove ../wt-<N>

REPLY-AND-RESOLVE PROCEDURE (step 11b, once per review round)

Every thread you acted on gets its own reply on that thread; one summary comment does
not discharge this, and resolving silently reads as "ignored".

Push first, reply second, resolve third.
 i. Push, then read real hashes: git -C <WORKTREE> log --oneline -n <count>
ii. Reply per thread using the databaseId of the thread's FIRST comment:
      gh api --method POST repos/<OWNER>/<REPO>/pulls/<PR>/comments/<id>/replies -f body="..."
    Fixed: name the commit and what changed. Rebutted: give the concrete reason with
    file:line, then the follow-up (none / issue #N filed / deferred and why). Never
    double-reply on a re-review round.
    Example of a fixed reply:
      "Addressed in a1b2c3d — clamp ageBoost to non-negative so future-dated items
      cannot lower the score." Do not just write "fixed" or "done".
iii. Resolve each replied thread, fixed and rebutted alike:
      gh api graphql -f query='mutation { resolveReviewThread(input:{threadId:"<node_id>"}) { thread { isResolved } } }'
iv. Top-level PR comments or review bodies have no thread: reply in place with
    gh pr comment <PR> --body "...".
 v. Re-read the thread list. Zero unresolved actionable threads is the step 12 gate.

Return AT MOST 6 lines: #N, PR number and URL, status (merged | awaiting-review |
blocked | failed), review rounds as "N threads: X fixed / Y rebutted", and any follow-up
you deferred, with the issue number if you filed one. No code, diffs, or file listings.
```

If a subagent reports `blocked` or `failed`, **stop the loop** and report. Later issues
usually branch on the failed one.

### Parent issues (the PR-per-parent pattern)

Some boards group work as one parent issue per intended PR (e.g. `#56 PR 1: Baseline
fixes` with six sub-issues). Two ways to run that, and the user picks in Phase 0:

- **One PR per sub-issue** (default, what the loop above does): scope with `--parent 56`,
  each child gets its own branch and PR, merged sequentially. The parent closes itself
  when the last sub-issue closes, and its board item moves to Done via the project's
  built-in "item closed" workflow.
- **One PR for the whole parent**: scope with `--issues 56 --include-parents`, and tell the
  implementer that the plan lives across the sub-issues. It works them as commits on one
  branch, the PR body lists `Closes #45`, `Closes #46`, … for every child, and step 14 sets
  Done on each child then the parent. Use this when the user has said the parent *is* the
  PR, as the CI plan for `ai-convobot` does.

## Phase 3.5 / 3.6 — Sonar (Sonar repos only)

Same as `jira-board-workflow`, with one substitution: tickets are GitHub issues. The
triage subagent creates them with `gh issue create -R OWNER/REPO --label security
--title ... --body-file ...` using the house body format (Description / Implementation
Plan / Acceptance Criteria), then `gh_board.py add` and `gh_board.py set ... --points P
--assignee ericfisherdev --status "Plan Created"`. The Phase 3.5 queue is then
`state ... --label security`.

## Phase 4 — Report

Run `state` once more and report:
- issues merged, with PR numbers
- anything left `Todo` / `In Progress` / blocked, and why
- cross-issue impacts planners raised
- **what is still open on the board outside this run's scope**, with a suggested next scope
- Sonar items, as in the Jira skill

Then **stop**.

## Orchestrator context rules

These rules now live under [Rules that hold every time](#rules-that-hold-every-time) near
the top of this file.

## Standing authorizations

Pre-authorized for board-workflow runs:
- taking a PR out of draft once CI passes
- merging once every required check is green on the PR's current head, with
  `--delete-branch` for the run's own feature branch
- replying to and resolving review threads on the run's own PRs, rebuttals included
- moving issues between the five Status values and closing an issue at Done

Still needs a check-in: force-pushing, deleting other branches, editing issues outside
the run's scope, changing board fields or options, enabling or disabling workflows.

## Known gotchas

- **"Known flake" is a claim, not a fact.** A flake documented in a repo's CLAUDE.md makes
  the label the default assumption, which is what lets a real regression through. Settle it
  with `job_history.py "<job name>"`: a flake fails intermittently on the same branch, while
  a regression fails every run on one branch while others stay clean, or only after a given
  timestamp. Failing 4-of-4 on your branch while siblings pass is not a flake.
- **Never conclude "nothing is required" from `required_status_checks` alone.** A branch can
  require approving reviews with no required checks, in which case that field reads null and
  the PR still cannot merge. `merge_readiness.py <PR>` reads protection and rulesets
  together — a brief built on a partial read gets passed into subagent prompts and costs
  them a denied merge attempt.

- **`project` scope.** `gh project` needs it and the default `gh auth login` does not
  grant it. On this machine `gh auth refresh -s project,read:project` hangs in the
  user's own terminal after browser approval; running the same command from a
  background Bash call, handing the user the device code, and polling the log works.
  The `ericfisherdev` token already has it (stored in `~/.config/gh/hosts.yml`).
- **Rewriting Status options blanks every item.** `updateProjectV2Field` with
  `singleSelectOptions` regenerates option ids. Add options before items exist, or re-set
  every item afterwards. `gh_board.py` always looks options up by name, never caches ids.
- **Number fields come back as floats.** `Points` reads as `1.0`; the table prints `1`.
- **Sub-issue and dependency REST endpoints take database ids**, not numbers:
  `POST /issues/<parent>/sub_issues -F sub_issue_id=<id>` and
  `POST /issues/<n>/dependencies/blocked_by -F issue_id=<id>`, where `<id>` is
  `gh api repos/O/R/issues/N --jq .id`.
- **Containers are structural.** An issue with `sub_issues_summary.total > 0` is a parent
  and is dropped from the queue. A tracking issue that only uses a task list (`- [ ] #N`)
  is *not* detected as a parent; convert it to real sub-issues.
- **The built-in "item closed → Done" project workflow** moves an item to Done when its
  issue closes, including via a PR's `Closes #N`. `gh_board.py set --status Done` still
  runs as the backstop and re-asserts the assignee.
- **PR title CI** (where present) rejects an uppercase subject or trailing period.
- **The PR title must carry `(#N)` and the body `Closes #N`.** The title keeps a merged
  PR traceable after the branch is deleted; the body line is what closes the issue.
- **Repo layouts vary.** Step 3 fetches `origin` and branches off `origin/HEAD`; the
  worktree goes in a sibling directory (`../wt-N`) so it never nests inside the checkout.
- **Whole-board runs are refused above 12 workable issues.** Ask for a scope.

## Reference

- [evals/test-prompts.md](evals/test-prompts.md) — three test prompts and the baseline without the skill.
