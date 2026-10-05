# Test prompts for plane-task-workflow

Run each prompt in a fresh session with the skill on and again with it off. Compare against the expected outcome.

## Prompt 1: normal run

> Work the Plane backlog for READ in ~/dev/ereader, the next 3 tasks.

Expected with skill: runs `plane_state.py state READ` and the glab preflight, then takes one task at a time through a `fable` planner subagent and a `sonnet` implementer subagent, each returning at most 6 lines. Records a `KEY | MR # | merged` ledger line per task, stops at 3 tasks, and reports why the run ended. The orchestrator never reads a diff or a work-item body.

Baseline without skill: reads work items and code in the main session, may plan all tasks up front, uses `gh` against a GitLab repo, and runs `glab mr merge` without `--auto-merge=false`.

## Prompt 2: halt for a person

> Run the Plane workflow for READ. If a task needs a decision from me, ask.

Expected with skill: when a planner or implementer returns `needs_human: <role> — <question>`, stops the loop immediately, runs `plane_state.py wait <KEY> --who "<role>"`, puts the actual question with its options to the user, and waits. After an answer it clears the flag and resumes. It does not start another task in the meantime.

Baseline without skill: skips the blocked task and carries on with the next one, or guesses an answer, and collects questions at the end of the run.

## Prompt 3: resume with in-flight and flagged tasks

> Work the next Plane tasks for READ epic READ-14 with --no-plan.

Expected with skill: preflight reports any `In Progress` task and any `!! WAITING ON HUMAN` task before new work starts and asks whether to resume or reset. With `--no-plan` the planner is skipped and the implementer is chosen by the `doc` label (document-task or code-task prompt). Blocked tasks are skipped and mentioned in the report.

Baseline without skill: starts a new task alongside the open one, ignores the `needs-human` label, and does not distinguish document tasks from code tasks.
