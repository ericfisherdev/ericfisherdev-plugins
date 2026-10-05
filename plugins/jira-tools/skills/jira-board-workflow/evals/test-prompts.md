# Test prompts for jira-board-workflow

Run each prompt in a fresh session with the skill on and again with it off. Compare against the expected outcome.

## Prompt 1: work an epic end to end

> Work the board for project FWDF, epic FWDF-40. Run these tickets through to Done.

Expected with skill: Phase 0 runs `board_state.py` with `--epic FWDF-40` and reports the table and verdict without the orchestrator reading any ticket body. Planners (one `fable` subagent per To Do ticket) run in parallel, every ticket ends `Plan Created` with points and an assignee, then one `sonnet` subagent per ticket works sequentially through PR, CI, review, merge and Done. The final report lists merged PRs and what is still open on the board outside the scope.

Baseline without skill: the session pages through Jira JSON itself, starts coding in the main context, and drifts into a single long session with no planning gate, no assignee invariant, and no per-ticket subagent.

## Prompt 2: unscoped board guardrail

> Work the board for NSTR.

Expected with skill: `board_state.py` exits non-zero because the project has more than 12 open tickets and no scope was given. The orchestrator stops and asks which tickets the run covers instead of inventing a scope or raising `--max-queue` itself.

Baseline without skill: picks an arbitrary slice of the backlog or starts on all open tickets without asking.

## Prompt 3: PR waiting on review

> One of the tickets in the run came back from its implementer as awaiting-review for PR 87. Carry on with the run.

Expected with skill: the orchestrator does not start the next ticket. It polls `merge_readiness.py 87` on a long interval without reading review bodies, spawns a fresh `sonnet` subagent to resume at step 11 when new review activity appears, or to finish steps 13 and 14 when the PR is merged, and asks the user after about two hours of silence.

Baseline without skill: moves on to the next ticket on top of an unmerged branch, or reads the full review bodies in the main session.
