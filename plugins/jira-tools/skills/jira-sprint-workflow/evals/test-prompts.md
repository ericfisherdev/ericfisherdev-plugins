# Test prompts for jira-sprint-workflow

Run each prompt in a fresh session with the skill on and again with it off. Compare against the expected outcome.

## Prompt 1: full sprint run

> Run the sprint for project NSTR.

Expected with skill: runs `sprint_state.py NSTR` first, stops and reports if external blockers or in-flight tickets exist, then plans every To Do ticket with parallel `fable` subagents (points set, assigned, moved to Plan Created) and implements them one at a time with `sonnet` subagents. The orchestrator keeps only a one-line-per-ticket ledger and never reads a diff or ticket body.

Baseline without skill: the main session reads tickets and code itself, works through them in one context, and has no dependency audit, assignment gate, or merge-readiness check.

## Prompt 2: plan only

> Start the sprint workflow for NES sprint 42 with --plan-only.

Expected with skill: planning phase only. Each planner returns at most 6 lines, every ticket ends at Plan Created with story points and the sprint owner as assignee, cross-ticket impacts are reported to the user, and no implementation subagent is spawned.

Baseline without skill: either starts implementing, or writes plans in chat without updating Jira points, assignee, or status.

## Prompt 3: PR waiting on review

> Work the sprint tickets for LRA. One of them is already in review with an open PR and an unresolved CodeRabbit thread.

Expected with skill: reports the in-flight ticket and asks whether to resume or reset it. When resumed, the review watch uses `merge_readiness.py`, fixes or rebuts each thread with a reply naming the commit or the reason, resolves it, and merges only when the verdict is mergeable. No admin override is used.

Baseline without skill: replies with a single summary comment or resolves threads silently, and may merge on a stale green or by bypassing branch protection.
