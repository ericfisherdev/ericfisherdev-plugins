# Test prompts for github-board-workflow

Run each prompt in a fresh session with the skill on and again with it off. Compare against the expected outcome.

## Prompt 1: scoped run from a parent issue

> Work this parent issue: ericfisherdev/ai-convobot --project 2 --parent 56. Run the whole thing from Todo through Done.

Expected with skill: `gh_board.py state` is run first and its table drives the queue. Each `Todo` issue gets one `board-planner` subagent in parallel, every issue is `Plan Created`, pointed, and assigned before Phase 3, then one `board-implementer` subagent per issue runs strictly one after another. The orchestrator keeps only a one-line ledger per issue and never reads a diff or an issue body.

Baseline without skill: lists issues with `gh issue list`, starts coding in the main session, and has no board status updates, points, or per-issue subagents.

## Prompt 2: unscoped board is refused

> Work the ai-convobot project board. Take everything from Todo through Done.

Expected with skill: Phase 0 `state` trips the guardrail (more than 12 open workable issues, no scope given). The orchestrator stops and asks which issues the run covers. It does not invent a scope or raise `--max-queue`.

Baseline without skill: picks an arbitrary slice of the board or tries to implement everything in one session.

## Prompt 3: external blocker and awaiting review

> Run these issues: ericfisherdev/ai-convobot --project 2 --issues 61,62. Issue 62 is blocked by an open issue that is not in this list.

Expected with skill: Phase 1 reports the external blocker and stops before planning. Once the scope is widened and a PR reaches `awaiting-review`, the orchestrator polls `merge_readiness.py` on a long interval with `ScheduleWakeup` (falling back to `/loop`) instead of reading review bodies, and never merges with an admin override.

Baseline without skill: ignores the dependency, implements both issues, and may merge past a blocked or unreviewed PR.
