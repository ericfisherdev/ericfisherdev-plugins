---
name: plane-task-workflow
description: Work a Plane project's backlog one task at a time, each carried start to finish — plan, implement, PR, merge, Done — before the next begins, capped at 10 tasks per run, delegating every task to a fresh subagent so the main context never accumulates. Use when the user asks to "work the Plane backlog", "run the Plane workflow", "work the next Plane tasks", or to take Plane work items from Todo through Done.
---

# Plane Task Workflow

Drives a Plane project's backlog from Todo to merged, **one task fully finished before
the next starts**. The orchestrator (you, in the main session) never writes code, never
reads a diff, and never reads a full work-item body. Every task is handled by
**subagents with their own context windows**, which is what keeps a ten-task run from
filling a 200k-token session.

There is no sprint or cycle here. Work is pulled from the project backlog in key order,
optionally narrowed to one epic.

## Invocation

```
/plane-task-workflow <PROJECT> --repo <path> [--epic <KEY>] [--limit N] [--no-plan]
```

- `PROJECT` — Plane project identifier, e.g. `READ`
- `--repo` — repository path. **Required**: nothing in Plane records where the code lives.
- `--epic` — restrict the queue to one epic's sub-issues, e.g. `--epic READ-14`
- `--limit` — tasks this run, default **10**, hard-capped at 10
- `--no-plan` — skip the per-task planning agent and implement the plan already on the
  work item. Use when the bodies were written recently against the current codebase.

## Why it is built this way

Each task is a **plan → implement → merge** cycle that completes before the next task is
picked up. That is deliberate and differs from the sprint workflow, which plans a whole
sprint in parallel first. Planning one task at a time means each plan is written against a
codebase that already contains the previous task's merged work — no plan goes stale while
it waits in a queue, and no cross-ticket conflict has to be predicted in advance.

The cost is lost parallelism. That is the intended trade.

Model per phase:

| Phase | Model | Why |
|---|---|---|
| Planning | `fable` | Research + plan writing against current code, one agent per task |
| Implementation | `sonnet` | Code, CI, merge — one agent per task |
| Orchestration | inherit | You only route and report |

## Phase 0 — Preflight

Run the state helper. **This is the only way you read Plane state** — never page through
Plane JSON yourself:

```sh
python ~/.claude/skills/plane-task-workflow/scripts/plane_state.py state <PROJECT>
```

It prints a per-epic roll-up plus a verdict: counts, anything in flight, anything blocked,
and `next task`. Add `--epic <KEY>` to narrow, `--json` to branch on fields.

Confirm before doing anything else:

- `glab auth status` is logged in to the repo's GitLab host
- `--repo` exists and is a git repository
- The helper reaches Plane (it exits non-zero with a clear message if not)

These repos live on the **self-hosted GitLab**, not GitHub, so everything MR-shaped goes
through `glab`. `gh` is not used by this workflow and will not resolve these projects.

Resolve the two glab values once, here, and pass them into every subagent prompt:

```sh
git -C <REPO_PATH> remote get-url origin
# ssh://git@192.168.0.16:2222/ericfisherdev/ereader.git
#          └── GLAB_HOST is the API host: 192.168.0.16:8929  (NOT the SSH port)
#                                         └── GLAB_REPO: ericfisherdev/ereader
export GITLAB_HOST=<GLAB_HOST>
glab repo view -R <GLAB_REPO>          # must succeed before the loop starts
```

**Every glab call needs both** `GITLAB_HOST` exported and `-R <GLAB_REPO>` — see the
host-mismatch gotcha below for why bare `glab` fails inside these worktrees.

Also check whether the project has CI at all:

```sh
glab ci list -R <GLAB_REPO>
```

"No pipelines available" plus no `.gitlab-ci.yml` in the repo means **there is no pipeline
gate**. Say so once in the preflight summary; the implementer's bar becomes the repo's
local gates, and step 7 is skipped rather than waited on.

Then:

1. If tasks are **in flight** (`In Progress`) from a previous run, report them and ask
   whether to resume or reset before starting new work. Do not start a new task alongside
   one that is already open.
2. If the helper prints `!! WAITING ON HUMAN`, those tasks are parked awaiting a person
   from an earlier run. Surface each one's question to the user **before starting any
   work** — they may be able to answer immediately, in which case clear the flag with
   `plane_state.py wait <KEY> --clear` and the task rejoins the queue. Never work around a
   flagged task by starting a different one without mentioning it.
3. If any queued task is **blocked** by an unfinished work item, the helper says so. Skip
   it and take the next actionable one; report the skip at the end.
4. Announce the plan: which project, which epic if narrowed, how many tasks this run.

**SonarQube is deliberately not part of this workflow.** No detection, no gate, no triage
phase. If Sonar coverage is wanted later it belongs here as a separate, explicit phase —
do not improvise it mid-run.

## The halt rule — a human being needed stops everything

**When a task needs a person, the entire run pauses. It does not skip the task and carry
on.** This is the single most important behaviour in the skill, and it overrides the
"keep going until the limit" instinct everywhere else.

"Needs a person" means the task cannot be completed correctly without a decision, an
approval, a credential, or information that only a human holds — an architectural choice,
a product name, an interview, access to a system, a judgement call between real options.
It does **not** mean the work is merely hard.

Either agent can raise it, and both must:

- **The planner** raises it *before* any code is written, by returning
  `needs_human: <role> — <the actual question>`. This is the better outcome: nothing is
  half-built.
- **The implementer** raises it when the need only becomes visible mid-task, by returning
  `needs_human: <role> — <question>` instead of a merged result.

When either returns `needs_human`, do all of this, in order:

1. **Stop the loop immediately.** Do not run `plane_state.py state` for a next task. Do not
   start another task even if the limit and the queue both allow it.
2. Flag the task so a future run cannot silently pick it up:
   ```sh
   python ~/.claude/skills/plane-task-workflow/scripts/plane_state.py wait <KEY> --who "<role>"
   ```
   The helper excludes flagged tasks from the queue and prints them as
   `!! WAITING ON HUMAN`.
3. **Ask the user the actual question.** Put the decision in front of them with the real
   options and the trade-offs, the same way any other blocking question would be asked.
   Do not paraphrase it as "this task is blocked" — they need the question itself.
4. **Wait.** This is a pause, not an abort.

Then, depending on the answer:

- **The user answers** → clear the flag, feed the answer to a fresh implementer subagent,
  finish the task, and **resume the loop** where it left off. The run continues normally.
  ```sh
  python ~/.claude/skills/plane-task-workflow/scripts/plane_state.py wait <KEY> --clear
  ```
- **The user cannot answer now** → leave the flag on, leave the task open, end the run, and
  report. The flag is what makes the next run skip it instead of stalling on it again.

Partial work already merged before the halt stays merged — it is additive and reverting it
helps nobody. Say so in the report so nobody thinks the task is untouched.

**Do not batch questions to the end of the run.** The point of pausing is that the answer
changes the work; collecting questions and asking them after ten tasks have been built on
guesses defeats it entirely.

## Phase 1 — The task loop

Repeat until `next task` is `(none actionable)` **or the run limit is reached**, whichever
comes first. Keep a ledger: one line per task, `KEY | PR # | merged|blocked|failed`.

Each iteration is one complete task:

1. Run `plane_state.py state <PROJECT> [--epic <KEY>]` to get `next task`.
2. **Stop if the ledger already holds `--limit` entries.** Go to Phase 2. Do not start an
   eleventh task because the queue still has items — the cap is the point of the run.
3. Move the task to In Progress and assign it, in one call:
   ```sh
   python ~/.claude/skills/plane-task-workflow/scripts/plane_state.py move <KEY> "In Progress" --assign eric
   ```
4. Unless `--no-plan`: spawn **one `fable` planner subagent** (prompt below). It returns at
   most 6 lines, including a `kind: code|document` verdict.
5. Spawn **one `sonnet` implementer subagent**, picking the prompt by kind:
   - the work item carries the **`doc` label**, or the planner returned `kind: document`
     → **document-task prompt**
   - otherwise → **code-task prompt**

   The label wins when the two disagree, and it is the only signal available under
   `--no-plan`. If a planner says `document` for an unlabelled item, add the label before
   dispatching so the next run agrees with this one.
6. Record the ledger line. **Do not read the diff, the PR body, or the work-item body.**
7. If the implementer reports `blocked` or `failed`, **stop the loop** and report. Do not
   skip ahead — later tasks in the same epic usually build on the failed one, and the
   work item is left `In Progress` on purpose so the next run sees it in flight.

### Planner prompt (fable)

```
Refresh the implementation plan for Plane work item <KEY>. Do NOT write implementation code.

Repository: <REPO_PATH>

1. Read the work item:
     python ~/.claude/skills/plane-task-workflow/scripts/plane_state.py show <KEY>
   It already has Description / Implementation Plan / Acceptance Criteria written from the
   program docs. Your job is to make the plan correct against the code as it stands TODAY,
   not to invent a new one.
2. Research every technology the task touches using context7 (resolve-library-id then
   query-docs). Prefer context7 over web search. Never guess an API — verify it.
3. Read the actual code the task will touch. Match existing patterns and conventions.
4. Rewrite ONLY the Implementation Plan section into a concrete, file-level plan: which
   files, which functions, which tests, in what order. Leave Description and Acceptance
   Criteria alone unless they are now factually wrong.
5. If the task is too large to land as one MR, say so explicitly and propose the split.
   Do not split it yourself.
5b. Decide whether this task produces CODE or a DOCUMENT. A document task ships an
   artifact — an ADR, a matrix, a charter, a runbook — and has no test suite to satisfy.
   Phase 0 tasks are all document tasks; so is any task whose acceptance criteria are
   "X is published / accepted / agreed" rather than "X behaves like Y".
6. Write the updated body back:
     PATCH /api/v1/workspaces/<WORKSPACE>/projects/<PROJECT_ID>/work-items/<ITEM_ID>/
     {"description_html": "<full body>"}
   Header: X-API-Key from ~/.plane_token. Get WORKSPACE/PROJECT_ID/ITEM_ID from the
   `show` output and `plane_state.py state <PROJECT> --json`.

7. HALT CHECK. Decide whether this task can be completed correctly WITHOUT a person. If it
   needs a decision, an approval, a credential, or information only a human holds — an
   architectural choice between real options, a product name, an interview, access to a
   system you cannot reach — then return `needs_human: <role> — <the actual question>` as
   your FIRST line and stop. Do not plan around the gap, do not pick a default, and do not
   write a plan whose first step is "decide X". Raising this before any code exists is the
   cheapest possible outcome.
   Needing a person is NOT the same as the work being hard or long.

Return AT MOST 6 lines: KEY, `kind: code` or `kind: document`, a one-line plan summary,
files to be touched, and whether the task should be split. If you are halting, the first
line is `needs_human: <role> — <question>` and the rest is context for it. Do not return
the plan body — it is on the work item.
```

### Code-task implementer prompt (sonnet)

```
Implement Plane work item <KEY> end to end. Repo <REPO_PATH>.

1. Read the plan:
     python ~/.claude/skills/plane-task-workflow/scripts/plane_state.py show <KEY>
   Follow its Implementation Plan. Its Acceptance Criteria are what "done" means.
2. Create a worktree off updated main (repos use a bare-clone layout: .bare + main/):
     git -C <REPO_PATH> worktree add <KEY> -b feature/<KEY>-<short-slug>
3. Implement. Match surrounding code. Write tests first where the repo's conventions
   expect it. Run the repo's own gates (make fmt / make lint / make test, or the
   equivalent) until green.
4. Stage: git add -A
5. Commit with Conventional Commits. The subject must be lowercase, no trailing period,
   and must name the specific thing that changed — never "address review findings" or
   "various improvements".
6. Push and open a DRAFT merge request. These repos are on the self-hosted GitLab — use
   glab, never gh. EVERY glab call needs the env var and -R:
     export GITLAB_HOST=<GLAB_HOST>
     git push -u origin feature/<KEY>-<short-slug>
     glab mr create -R <GLAB_REPO> --draft --yes \
       --source-branch feature/<KEY>-<short-slug> --target-branch <DEFAULT_BRANCH> \
       --title "<KEY>: <conventional commit subject>" \
       --description "<what changed and why>"
   Note the MR's IID (the !N number) from the output.
7. PIPELINE: only if preflight said this project HAS CI.
     glab ci status -R <GLAB_REPO> --branch feature/<KEY>-<short-slug>
   Fix failures and push until it passes. If preflight said there is no pipeline, SKIP
   this step entirely — the local gates from step 3 are the bar. Do not wait on a
   pipeline that will never run, and do not invent one.
8. Take the MR out of draft: glab mr update <IID> -R <GLAB_REPO> --ready
9. MERGE GATE: pipeline green on the MR's CURRENT head (or local gates green where there
   is no pipeline), then:
     glab mr merge <IID> -R <GLAB_REPO> --rebase --yes --auto-merge=false
   `--auto-merge` DEFAULTS TO TRUE, which queues merge-on-pipeline-success and returns
   before anything is merged. Always pass --auto-merge=false: this workflow verifies green
   itself and then merges, so that the ledger line means what it says.
   "Green" means the pipeline for the head commit you are about to merge — re-read status
   after any push rather than trusting an earlier pass.
   If the pipeline fails and you cannot fix it, stop and report — do not merge.
   If the merge is refused for any other reason — a required approval, a protected branch —
   STOP and report. Do not reach for an admin override: bypassing branch protection is
   the user's call, not this workflow's.
10. Confirm it actually merged: glab mr view <IID> -R <GLAB_REPO> | grep -i merged
11. Update local main: git -C <REPO_PATH>/main pull --ff-only
12. Close the task and remove the worktree:
      python ~/.claude/skills/plane-task-workflow/scripts/plane_state.py move <KEY> Done --assign eric
      git -C <REPO_PATH> worktree remove <KEY>

HALT RULE — applies at every step above. The moment you find that finishing this task
correctly requires a person — a decision between real options, an approval, a credential,
information you cannot obtain — STOP and return `needs_human: <role> — <the actual
question>` as your first line. Do not guess, do not pick a default, do not invent a
placeholder value and carry on, and do not merge a version that bakes in an assumption.
If you had already merged something before hitting this, say what merged and that the task
is unfinished. Needing a person is NOT the same as the work being hard.

Return AT MOST 6 lines: KEY, MR IID and URL, merged yes/no, and any follow-up work you
had to defer. If you are halting, the first line is `needs_human: <role> — <question>`.
Do not return code, diffs, or file listings.
```

### Document-task implementer prompt (sonnet)

Same shape, different bar: the deliverable is a file, and there is no test suite to make
green. Everything about branches, MRs and the merge gate is identical.

```
Produce the deliverable for Plane work item <KEY>. Repo <REPO_PATH>.

1. Read the work item:
     python ~/.claude/skills/plane-task-workflow/scripts/plane_state.py show <KEY>
   This is a DOCUMENT task: it ships an artifact, not code. Its Acceptance Criteria name
   the artifact and what must be true of it.
2. Create a worktree off updated main:
     git -C <REPO_PATH> worktree add <KEY> -b docs/<KEY>-<short-slug>
3. Write the artifact to the conventional location:
     - ADRs            -> docs/adr/ADR-NNN-<slug>.md, numbered per the task
     - everything else -> docs/<slug>.md unless the task names a path
   Match the format of any sibling document already in that directory. If the directory
   is empty, establish the obvious convention and say so in your return.
4. Where the task requires information you cannot obtain — interview responses, a
   sponsor's decision, a name only the team can choose — write the document with those
   sections marked "OPEN — needs <who>" rather than inventing content. Fabricated
   discovery findings are worse than a visible gap. List every such gap in your return.
5. Commit with Conventional Commits, type `docs`, lowercase subject, no trailing period.
6. Push and open a DRAFT MR, then follow steps 7-12 of the code-task prompt exactly
   (glab, --auto-merge=false, verify merged, pull main, move to Done, remove worktree).
   The only difference: if there is no pipeline, local lint on the markdown is the bar.

Return AT MOST 6 lines: KEY, MR IID and URL, merged yes/no, the artifact path, and every
"OPEN — needs X" gap you left. Do not return the document body.
```

## Phase 2 — Report

When the loop ends — limit reached, queue empty, a failure, or a halt awaiting a person —
run `plane_state.py state` once more and report:

- **anything waiting on a human, first and unmissably**, with the question and who is
  needed. This leads the report; everything else is context. A run that ends on a halt is
  reporting a question, not a result.
- tasks merged this run, with MR numbers
- the ledger line for anything blocked or failed, and why
- tasks skipped because they were blocked by an unfinished work item
- **why the run ended**: limit reached, empty queue, failure, or halted for a person. Say
  which, because "10 done, 37 remaining", "all done", and "stopped at 2 waiting on you"
  look identical in a summary otherwise
- any task a planner flagged as needing a split

Then **stop**. Do not start another run, even with tasks remaining. A second run is the
user's call.

## Orchestrator context rules

These are the point of the whole skill. Violating them defeats it.

- **Never** read work-item bodies, source files, diffs, PR bodies, or CI logs in the main
  session. Subagents do that in their own context.
- Your entire working memory is the ledger: one line per task.
- Cap every subagent's return at ~6 lines and say so in the prompt.
- If you find yourself with a large tool result in context, that is a bug in how you
  delegated — push that work into a subagent next time.

## Standing authorizations

For workflow runs the user has pre-authorized, so do not stop to ask each time:

- taking an MR out of draft once the pipeline passes
- merging once the pipeline is green on the MR's current head
- moving work items between states and assigning them to eric

Everything else consequential — force-pushing, deleting branches other than the merged
feature branch, editing work items outside the queue, creating or deleting Plane states —
still needs a check-in.

## The state helper

```sh
plane_state.py state <PROJECT> [--epic KEY] [--limit N] [--probe N] [--json]
plane_state.py show  <KEY> [--no-body]
plane_state.py move  <KEY> "<state name>" [--assign <name-or-email>]
plane_state.py wait  <KEY> [--who "<role>"] [--clear]
```

`wait` sets or clears the `needs-human` label, which is how "this is parked awaiting a
person" survives between runs — Plane's five states cannot express it. A flagged task is
excluded from the queue and printed as `!! WAITING ON HUMAN`. The label list is read and
merged rather than overwritten, so flagging a task does not strip its `doc` label and
silently change which implementer prompt it routes to.

Config, environment first then fallback:

| Variable | Default |
|---|---|
| `PLANE_BASE_URL` | `http://192.168.0.16:8090` |
| `PLANE_WORKSPACE` | `ericfisherdev` |
| `PLANE_API_KEY` | contents of `~/.plane_token` |

## Known gotchas

- **The API key is rate-limited** — the stack sets `API_KEY_RATE_LIMIT=60/minute`. A
  `state` call costs roughly 4 + `--probe` requests. The helper backs off and retries on
  429, but do not sit in a polling loop against it. `--probe` defaults to 3 for this
  reason; raising it costs one request per extra task checked.
- **This Plane build has no Epic work-item type.** `issue_types` is empty and there is no
  project toggle — Epics are an EE surface. Phases are ordinary work items carrying the
  `epic` label, with tasks attached by `parent`. The helper treats *any* item with a
  parent as a workable task and any item without one as an epic. If someone creates a
  top-level task it will be read as an epic — give every task a parent.
- **`assignees` is `write_only` in the v1 serializer.** You can set it, you cannot read it
  back; a GET always shows `assignees: null`. Never test assignment by reading it.
- **States are matched by group, not name.** Plane's defaults are Backlog, Todo, In
  Progress, Done, Cancelled, mapping to groups `backlog`, `unstarted`, `started`,
  `completed`, `cancelled`. Renaming a state is safe; the helper keys off the group.
  There is **no "In Review" state by default** — a PR being open is represented by the
  task sitting in `In Progress`. If you add one, `move <KEY> "In Review"` will find it.
- **Work-item keys resolve natively**: `GET /api/v1/workspaces/<slug>/issues/READ-16/`
  returns the item. No need to search by sequence number.
- **Deletes are soft.** A deleted work item keeps its row and its `sequence_id` is not
  reused, so key numbering has gaps. That is expected, not corruption.
- **These repos are on self-hosted GitLab, not GitHub.** `gh` cannot resolve them —
  `gh repo view ericfisherdev/ereader` returns "Could not resolve to a Repository". All MR
  work goes through `glab`. One-time auth against the instance, which serves plain HTTP on
  a non-default port and SSH on 2222:
  ```sh
  glab auth login --hostname 192.168.0.16:8929 --api-protocol http --git-protocol ssh --stdin < token.txt
  ```
  The token is a GitLab personal access token with `api` scope — not the Plane key and not
  an SSH key.
- **glab cannot match the remote to the host on its own here, so bare `glab` fails**
  inside these worktrees with *"None of the git remotes configured for this repository
  point to a known GitLab host. Configured remotes: 192.168.0.16."* The remote is
  `ssh://git@192.168.0.16:2222/...`, from which glab derives the host `192.168.0.16`,
  while the authenticated host is `192.168.0.16:8929` — SSH port versus HTTP port. Setting
  `GITLAB_HOST` alone does **not** fix it (it then complains no remote corresponds to the
  variable). The combination that works, verified: `GITLAB_HOST` exported **and** an
  explicit `-R <owner>/<repo>` on every call.
  A permanent alternative, if you would rather not carry `-R`: re-auth with the git host
  and API host split apart, so the remote matches what glab expects —
  `glab auth login --hostname 192.168.0.16 --api-host 192.168.0.16:8929 --api-protocol http --git-protocol ssh --stdin`.
  Until that is done, `-R` is not optional.
- **`glab mr merge --auto-merge` defaults to true.** A bare `glab mr merge` sets
  merge-when-pipeline-succeeds and returns immediately, so the command can report success
  while nothing has merged. Always pass `--auto-merge=false`, and verify with
  `glab mr view <IID>` before moving the task to Done.
- **Conventional Commits** — lowercase subject, no trailing period. Most common failure in
  the sprint workflow; assume it here too, and expect the same of the MR title.
- **Not every task is a code task.** Phase 0's four are interviews, ADRs and program
  setup; the epic doc says outright "No production code in this phase." Those carry the
  `doc` label and route to the document-task prompt. Applying the label to future non-code
  tasks is a manual step nobody will remember — when a planner returns `kind: document`
  for an unlabelled item, add the label then.

## Maximum-freshness variant

Subagents give a fresh context but share the session's process. For a genuinely new process
per task, drive the loop headlessly, using **Plane as the state store** so each invocation
rediscovers where it is:

```sh
for i in $(seq 1 10); do
  KEY=$(python ~/.claude/skills/plane-task-workflow/scripts/plane_state.py state READ --json \
        | python -c 'import json,sys; print(json.load(sys.stdin)["next_task"] or "")')
  [ -z "$KEY" ] && break
  claude -p "Use the plane-task-workflow skill's planner then implementer procedure for $KEY only."
done
```

Each `claude -p` is a brand-new session, and the `seq 1 10` is the run cap. Slower and
harder to supervise, but nothing carries over between tasks at all.
