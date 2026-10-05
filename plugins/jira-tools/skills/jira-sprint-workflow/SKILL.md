---
name: jira-sprint-workflow
description: Run a full Jira sprint end to end — dependency audit, per-ticket implementation planning with story points, then sequential implement/review/merge — delegating every ticket to a fresh subagent so the main context never accumulates. Use when the user asks to "run the sprint", "work the sprint", "start the sprint workflow", or to work a sprint's tickets from To Do through Done.
---

# Jira Sprint Workflow

Drives an entire sprint from planning to merged. The orchestrator (you, in the main
session) never writes code, never reads a diff, and never reads a full ticket body.
Every ticket is handled by a **subagent with its own context window**, which is what
keeps a 20-ticket sprint from filling a 200k-token session.

## Contents

- Needs
- Rules that hold every time
- Invocation
- Subagent models
- Phase 0 — Preflight
- Phase 1 — Dependency audit
- Phase 2 — Planning (parallel, Fable)
- Phase 3 — Implementation (sequential, Sonnet)
- Phase 3.5 — Security hotspot sweep (Sonar repos only)
- Phase 3.6 — Residual Sonar triage (Sonar repos only)
- Phase 4 — Report
- Known gotchas
- SonarQube mode (auto-detected)
- Maximum-freshness variant
- Files in this skill

## Needs

- `gh` — GitHub CLI, authenticated (`gh auth status`); install with `pacman -S github-cli`. Also `git`, for worktrees.
- `curl` — used to set story points, which `update_jira_issue.py` cannot do.
- python3 (3.8+) — the scripts in this skill use the standard library only.
- Environment variables `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` for Jira access; `SONARQUBE_URL` and `SONARQUBE_TOKEN` as well on repos where Sonar is on.
- Scripts from the other skills of this same plugin (jira-tools), reached as `${CLAUDE_PLUGIN_ROOT}/skills/<skill>/scripts/<script>.py`:
  `jira-issue/scripts/fetch_jira_issue.py`, `update-issue/scripts/update_jira_issue.py`, `create-issue/scripts/create_jira_issue.py`.
- The `sonar-triage` skill (same plugin) and the `address-pr-reviews` skill, which implementers invoke during Sonar cleanup and review handling; the context7 MCP server, which planners use to verify APIs.

## Rules that hold every time

### Orchestrator context rules

These are the point of the whole skill. Violating them defeats it.

- **Never** read ticket descriptions, source files, diffs, PR bodies, or CI logs in the
  main session. Subagents do that in their own context.
- Your entire working memory is the ledger: one line per ticket.
- Cap every subagent's return at ~6 lines and say so in the prompt.
- If you find yourself with a large tool result in context, that is a bug in how you
  delegated — push that work into a subagent next time.

### Standing authorizations

For sprint-workflow runs the user has pre-authorized, so do not stop to ask each time:
- taking a PR out of draft once CI passes
- merging once every required check is green on the PR's current head
- replying to review threads on the sprint's own PRs, and resolving the threads you
  replied to — including ones you rebutted

Everything else consequential — force-pushing, deleting branches other than the merged
feature branch, editing tickets outside the sprint — still needs a check-in.

### Assignment invariant

Every ticket is assigned to the sprint owner the moment it
leaves `To Do` (at `Plan Created`), and **no ticket may reach `Done` unassigned** — the
Done transition re-asserts the assignee as a backstop. The owner here is **Eric Fisher**
(`update_jira_issue.py --assignee` does a partial, case-insensitive match on Jira display
name); change that string if the sprint owner ever changes. `--assignee` and `--status`
can be passed in one call — the script sets fields before it transitions.

## Invocation

```
/jira-sprint-workflow <PROJECT> [--sprint <id>] [--repo <path>] [--no-sq] [--plan-only|--work-only]
```

- `PROJECT` — Jira project key (e.g. `NSTR`, `NES`, `LRA`)
- `--sprint` — sprint id; defaults to the **active** sprint, else the earliest **future** one
- `--repo` — default repository path; per-ticket overrides come from the ticket itself
- `--no-sq` — force the SonarQube steps off. **Not normally needed**: Sonar is
  auto-detected from the repo, see below. Use it only to skip Sonar on a repo that does
  have a project — e.g. the analysis is down and you do not want it blocking the run.
- `--plan-only` — stop after planning · `--work-only` — assume planning is done

## Subagent models

Do not switch the session model. Spawn each subagent with a `model` override: `fable` for
planning (Phase 2), `sonnet` for implementation (Phase 3), `opus` for Sonar security triage
(Phase 3.5). You, the orchestrator, stay on whatever model the session is already using and
only route and report. Why subagents are used instead of clearing context, and why each
phase gets its model: [references/background.md](references/background.md).

## Phase 0 — Preflight

Run the state helper. **This is the only way you read sprint state** — never page through
Jira JSON yourself:

```sh
python "${CLAUDE_SKILL_DIR}/scripts/sprint_state.py" <PROJECT>
```

It prints one table plus a verdict: `planning complete`, external blockers, in-flight
tickets, and `next ticket`. Add `--sprint <id>` to target a specific sprint, `--json` if
you need to branch on fields.

Confirm before doing anything else:
- `gh auth status` is logged in

### The helper scripts

Five scripts back this workflow, all in `${CLAUDE_SKILL_DIR}/scripts/`. Two are
sprint-specific: `sprint_state.py` and `sonar_state.py` (the `sonar-triage` skill in this
same plugin also calls `sonar_state.py`). The other three, `ci_failure.py`, `job_history.py`
and `merge_readiness.py`, are repo-scoped helpers shared with the board workflows; they
import the small `gh_common.py` module that sits beside them. They exist for one reason:
each collapses a pile of API JSON into a few lines plus a verdict, so state can be read
without loading payloads into context. Use them instead of hand-rolling `gh` chains, in the
orchestrator **and** in subagent prompts.

| Need | Command | Exit status |
|---|---|---|
| Sprint state, next ticket | `sprint_state.py <PROJECT>` | 0 |
| Is this repo analysed by Sonar | `sonar_state.py key <REPO_PATH>` | 0 analysed / 1 not |
| Why is CI red | `ci_failure.py --pr N` (or `--branch`, `--run`) | 0 green / 1 failing |
| Can this PR merge, and what blocks it | `merge_readiness.py <PR>` | 0 mergeable / 1 blocked |
| Is this job a flake or really broken | `job_history.py "<job name>"` | 0 |

All of them take `--repo PATH` or `--slug OWNER/NAME`; `--repo` understands the
bare-clone-plus-worktrees layout, so pass the directory you think of as the repo.
Exit code 2 always means "could not answer", never "the answer is no".

Two of them replace judgement calls that have gone wrong before:

- **`merge_readiness.py` is the only sanctioned way to answer "can this merge?"** It reads
  the PR state, the checks on the *current* head, the review decision, unresolved threads,
  classic branch protection **and** rulesets together. Reading one of those alone is how a
  green PR ends up BLOCKED with no failing check to explain it: checking only
  `required_status_checks` on a branch whose rule is a *review* requirement returns nulls
  and looks like "nothing is required". A brief built on a partial read gets passed into
  subagent prompts and costs them a denied merge attempt.
- **`job_history.py` settles the flake question with evidence, not reputation.** It counts a
  named job's pass/fail record per branch and distinguishes three shapes: interleaved
  passes and failures (a genuine flake), a branch that fails every time while others are
  clean (a real regression), and failures that are all newer than the passes (something
  landed and broke it, reported with the timestamp). Run it before accepting any "known
  flake" claim. A flake documented in a repo's CLAUDE.md makes "flake" the default
  assumption, which is exactly how a real regression gets waved through. Failing 4-of-4 on
  your branch while five sibling branches pass is not a flake.

**Resolve Sonar once, here, and carry the answer through the run.** Whether the Sonar
steps happen is a property of the repo, not something the invoker has to remember:

```sh
python "${CLAUDE_SKILL_DIR}/scripts/sonar_state.py" key <REPO_PATH>
```

- **exit 0** — prints the project key. Sonar steps are ON. Pass that key to step 10 and
  Phases 3.5/3.6; never construct or guess one, it is read from the repo's own
  `sonar-project.properties`.
- **exit 1** — the repo has no `sonar-project.properties`. Sonar steps are OFF. This is
  a normal outcome, not an error: say so once in the Phase 0 summary and skip them.
- **any other failure** — e.g. a properties file with no `sonar.projectKey`. That is
  misconfiguration; stop and report rather than quietly proceeding without Sonar.

With Sonar ON, also confirm `SONARQUBE_URL` and `SONARQUBE_TOKEN` are set and the key
resolves against the server (`sonar_state.py gate <KEY>`). A key that exists in the file
but not on the server is a stop-and-report, not something to work around.

`--no-sq` forces OFF regardless of detection.

## Phase 1 — Dependency audit

From the Phase 0 table:

1. If **external blockers** are listed (a blocker that is neither `Done` nor in this
   sprint), **stop and report**. The sprint is not self-contained; the user decides
   whether to pull the blocker in or defer the ticket.
2. If tickets are **in flight** (`In Progress` / `In Review`) from a previous run, report
   them and ask whether to resume or reset them before starting new work.
3. Otherwise continue.

## Phase 2 — Planning (parallel, Fable)

Skip entirely if `planning complete : True`, or if `--work-only`.

Spawn **one `fable` subagent per `To Do` ticket, all in parallel**. Every planner gets the
full sprint ticket list (keys + summaries only) so it can judge cross-ticket impact —
that requirement comes from the source workflow and is the reason planners see their
siblings.

Planner prompt template. Send verbatim, filling <placeholders>:

```
Plan Jira ticket <KEY> in project <PROJECT>. Do not write any implementation code.

Repository: <REPO_PATH>
Other tickets in this sprint (for cross-impact analysis only):
<KEY: summary list>

Steps:
1. Read the ticket: python ${CLAUDE_PLUGIN_ROOT}/skills/jira-issue/scripts/fetch_jira_issue.py <KEY>
2. Research every technology the ticket touches using context7 (resolve-library-id then
   query-docs). Prefer context7 over web search. Never guess an API — verify it.
3. Read the actual code the ticket will touch. Match existing patterns and conventions.
4. Judge whether this ticket forces changes to any sibling ticket above. Say so explicitly.
5. Rewrite the ticket's Implementation Plan section with a concrete, file-level plan.
   Keep the existing Description and Acceptance Criteria unless they are now wrong.
6. Estimate story points (Fibonacci: 1,2,3,5,8,13). 8+ means it should be split — say so.
7. Update the ticket:
   python ${CLAUDE_PLUGIN_ROOT}/skills/update-issue/scripts/update_jira_issue.py <KEY> \
     --description "<full markdown body>"
   Set points with this call (update_jira_issue.py has no points option). It prints
   nothing on success and fails with a non-zero exit on an HTTP error:
     curl -sSf -u "$JIRA_EMAIL:$JIRA_API_TOKEN" -X PUT -H "Content-Type: application/json" \
       "$JIRA_BASE_URL/rest/api/3/issue/<KEY>" -d '{"fields":{"customfield_10016":<POINTS>}}'
   Then move it AND assign it to the sprint owner in a single call — a ticket must
   never advance out of To Do unassigned:
     ... update_jira_issue.py <KEY> --status "Plan Created" --assignee "Eric Fisher"

Return AT MOST 6 lines: KEY, points, one-line plan summary, and any cross-ticket impact
you found. Do not return the plan body — it is already on the ticket.
```

After the fan-out, re-run `sprint_state.py`. **Every ticket must be `Plan Created`, with
points, and assigned to Eric Fisher before Phase 3 begins** — that is a hard gate in the
source workflow. If any planner left a ticket unassigned, assign it before continuing
(`update_jira_issue.py <KEY> --assignee "Eric Fisher"`). Report any
cross-ticket impacts the planners surfaced; if a planner says a sibling needs altering,
raise it with the user before working.

Stop here if `--plan-only`.

## Phase 3 — Implementation (sequential, Sonnet)

Loop until `next ticket` is `(none actionable)`. **One ticket at a time** — the next
ticket starts only after the previous one is merged and `main` is updated, because each
ticket rebases onto the last.

Each iteration:
1. Run `sprint_state.py` to get `next ticket` (lowest-numbered `Plan Created`, unblocked).
2. Spawn **one `sonnet` subagent** with the prompt below.
3. Record one line in your ledger: `KEY | PR # | merged|awaiting-review|blocked|failed`.
4. Move on. **Do not read the diff, the PR body, or the ticket.**

### Handling `awaiting-review` (orchestrator-driven watch)

Subagents idle badly on long async waits, so when an implementer hands back
`awaiting-review` with a PR number, **you** own the watch — but stay within the context
rules: poll state only, never read the review bodies yourself.

1. Do **not** start the next ticket — it rebases on this one.
2. Poll on a long interval (~10 min; `ScheduleWakeup`/`/loop`, never a tight loop):
   ```sh
   python "${CLAUDE_SKILL_DIR}/scripts/merge_readiness.py" <N> --repo <REPO_PATH>
   ```
   One verdict line tells you whether it is mergeable or exactly what still blocks it —
   a missing approval, a failing check, an unresolved thread. Do not read review bodies.
3. Branch on the result:
   - `state: MERGED` → spawn a short `sonnet` subagent: "Resume ticket <KEY>: PR <N> is
     merged. Do steps 13–14 of the implementer procedure (update main, move to Done,
     remove worktree)." Ledger → `merged`, continue the Phase 3 loop.
   - New review activity (any review or unresolved thread newer than the hand-back) →
     spawn a fresh `sonnet` subagent: "Resume ticket <KEY> at step 11 of the implementer
     procedure for PR <N> in <REPO_PATH>, worktree <KEY>. Address the reviews, and after
     pushing run the reply-and-resolve procedure in
     ${CLAUDE_SKILL_DIR}/references/reply-and-resolve.md — reply on each individual thread
     naming the commit that fixed it, or the reason plus follow-up if you are rebutting,
     then resolve it. Carry the PR through steps 11–14." Same 6-line return contract.
   - No activity → keep polling. After ~2 hours with no reviewer activity, report to the
     user and ask whether to merge under the standing authorization (CI green, no
     changes requested) or keep waiting.

Implementer prompt template. Send verbatim, filling <placeholders>:

```
Implement Jira ticket <KEY> end to end, in project <PROJECT>, repo <REPO_PATH>.

Copy this checklist and track progress:

- [ ] Step 1: Move the ticket to "In Progress"
- [ ] Step 2: Read the Implementation Plan
- [ ] Step 3: Create the worktree
- [ ] Step 4: Implement, test, and pass the repo gates
- [ ] Step 5: Stage the work
- [ ] Step 6: Commit with Conventional Commits
- [ ] Step 7: Push, open the draft PR, move to "In Review"
- [ ] Step 8: Wait for CI green
- [ ] Step 9: Take the PR out of draft
- [ ] Step 10: Sonar cleanup (Sonar repos only)
- [ ] Step 11: Review watch
- [ ] Step 12: Merge gate, then merge
- [ ] Step 13: Update local main
- [ ] Step 14: Move to "Done" and remove the worktree

1. Move <KEY> to "In Progress".
2. Read the ticket's Implementation Plan and follow it.
3. Create a worktree off updated main (repos use a bare-clone layout: .bare + main/):
     git -C <REPO_PATH> worktree add <KEY> -b feature/<KEY>-<short-slug>
4. Implement. Match surrounding code. Write tests. Run the repo's own gates
   (make fmt / make lint / make test, or the repo equivalent) until green.
5. Stage the work: git add -A
6. Commit with Conventional Commits. The subject must be lowercase with no trailing
   period, and must name the specific thing that changed — never "address review
   findings" or "various improvements".
7. Push and open a DRAFT PR against the fork (ericfisherdev/<repo>), base = default branch.
   Move <KEY> to "In Review".
8. Wait for CI. Fix failures and push until every check passes. To see WHY a run is
   red, use the helper rather than paging through logs — it prints the failing job,
   the failing step, and the few decisive log lines:
     python "${CLAUDE_SKILL_DIR}/scripts/ci_failure.py" --pr <N> --repo <REPO_PATH>
   It exits 0 on green and 1 on failure, so it doubles as the wait condition. Before
   you write off any failure as a known flake, prove it with:
     python "${CLAUDE_SKILL_DIR}/scripts/job_history.py" "<job name>" --repo <REPO_PATH>
9. Take the PR out of draft: gh pr ready <N>
10. [Sonar repos only] Clean up what THIS PR introduced, using the sonar-triage skill in fix
    mode. Run it only once CI is green and the PR is out of draft (step 9), because
    Sonar's PR analysis is what this reads and it is triggered by the pushed head:
      /sonar-triage <SONAR_KEY> --pr <N> --repo <REPO_PATH>
    Scope: findings this PR ADDED. Sonar's PR analysis reports new-code findings, and
    that is the whole remit here. Do NOT widen it to pre-existing findings on main —
    those are collected as tickets at the end of the sprint (Phase 3.6), and dragging
    them into a feature PR bloats the diff and blocks the ticket on unrelated work.
    The skill fixes and pushes on this PR's own branch; it never files Jira issues in
    --pr mode, and it never resolves anything in Sonar.
    Sonar analysis is asynchronous: if the PR has no analysis yet, WAIT and re-check
    rather than reading "no findings" as a clean bill of health.
    If it pushed a fix, CI re-runs — go back to step 8 and wait for green again before
    continuing. Do not merge on a stale green.
11. REVIEW WATCH: once the PR is out of draft (step 9) it is visible to reviewers —
    humans, CodeRabbit, or the pr-review-bot skill running elsewhere. Watch it until
    it is merged. Each watch cycle, read:
      python "${CLAUDE_SKILL_DIR}/scripts/merge_readiness.py" <N> --repo <REPO_PATH>
    which reports the PR state, the checks on the current head, the review decision,
    the unresolved-thread count and the branch's actual protection rules in one pass.
    Then act on the FIRST matching rule:
    a. PR is MERGED (a reviewer or bot merged it for you) → skip straight to step 13.
    b. CHANGES_REQUESTED, or any unresolved review thread with an actionable finding →
       address the reviews using the address-pr-reviews skill (evaluate each finding
       against the real code, fix or rebut), then run the reply-and-resolve procedure
       below — it is not optional and it is not a summary comment. Commit fixes under
       the house commit rules (step 6), push, wait for CI green on the new head
       (step 8), re-run step 10 on a Sonar repo if the fix touched code, then keep
       watching for the re-review.
    c. APPROVED, zero unresolved threads, CI green on the current head → go to step 12
       and merge yourself.
    d. No new activity → wait and re-check. Never busy-poll: use the Monitor tool with
       an until-condition, or `gh pr checks <N> --watch` while CI is the thing pending.
       Do NOT end your turn to wait for a notification — none is coming, and the run
       stalls until the orchestrator notices and nudges you. Waiting is something you
       do inside a turn, with a blocking watch, not by handing control back.
       If there is no reviewer activity for ~30 minutes total, STOP watching and return
       to the orchestrator with status `awaiting-review` plus the PR number — do not
       idle forever inside the subagent.
12. MERGE GATE: confirm it mechanically before merging — one command answers the whole
    gate (state, checks on the current head, review decision, unresolved threads,
    branch protection and rulesets), and exits 1 with the specific blockers if not:
      python "${CLAUDE_SKILL_DIR}/scripts/merge_readiness.py" <N> --repo <REPO_PATH>
    Every required check green on the PR's CURRENT head AND zero unresolved review
    threads (actionable comments of ANY severity must be fixed or rebutted-and-resolved
    via step 11b first — never merge over an open finding), then:
      gh pr merge <N> --rebase
    "Green" means the run for the head commit you are about to merge — re-read the
    checks after any push from step 10 or 11 rather than trusting an earlier pass. On a
    Sonar repo the SonarQube check is part of that set, and because the scan waits on
    the quality gate, a green check is a passed gate.
    If a required check fails and you cannot fix it, stop and report — do not merge.
    If the merge is refused for a reason other than a failing check — a required
    review, a protected branch — STOP and report it. Do not reach for an admin
    override: bypassing branch protection is the user's call, not this workflow's.
13. Update local main: git -C <REPO_PATH>/main pull --ff-only
14. Move <KEY> to "Done", assigning it to Eric Fisher in the same call so the transition
    can never land unassigned (it is normally already assigned from planning; this call
    is the hard backstop for the invariant "no ticket reaches Done unassigned"):
      ... update_jira_issue.py <KEY> --assignee "Eric Fisher" --status "Done"
    Then remove the worktree.

REPLY-AND-RESOLVE PROCEDURE (invoked by step 11b, once per review round)

Read ${CLAUDE_SKILL_DIR}/references/reply-and-resolve.md and follow it exactly. It covers the
order (push, reply on each thread, resolve, re-read the thread list) and the wording rules
for fixed and rebutted findings.

Return AT MOST 6 lines: KEY, PR number and URL, status (merged | awaiting-review |
blocked | failed), review rounds handled as "N threads: X fixed / Y rebutted", and
any follow-up work you deferred, with the Jira key if you filed one. Do not return
code, diffs, or file listings.
```

If a subagent reports `blocked` or `failed`, **stop the loop** and report to the user.
Do not skip ahead to the next ticket — later tickets usually rebase on the failed one.
`awaiting-review` is not a failure — handle it with the orchestrator-driven watch above.

## Phase 3.5 — Security hotspot sweep (Sonar repos only)

Skip this phase entirely when Phase 0 resolved Sonar to OFF. It runs **after every sprint
ticket is merged** and loops until Sonar is clean. List what is outstanding with:

```sh
python "${CLAUDE_SKILL_DIR}/scripts/sonar_state.py" hotspots <SONAR_KEY>
```

Zero hotspots means the sweep is done and you go to Phase 4. Otherwise spawn one `opus`
subagent to triage and file tickets, run the Phase 3 loop over the tickets it created, and
re-check. The full procedure and the Opus prompt are in
[references/sonar-phases.md](references/sonar-phases.md), section "Phase 3.5". Before sending
that prompt, replace its three script placeholders with these absolute paths:

- `<SONAR_STATE>` is `${CLAUDE_SKILL_DIR}/scripts/sonar_state.py`
- `<CREATE_ISSUE>` is `${CLAUDE_PLUGIN_ROOT}/skills/create-issue/scripts/create_jira_issue.py`
- `<UPDATE_ISSUE>` is `${CLAUDE_PLUGIN_ROOT}/skills/update-issue/scripts/update_jira_issue.py`

## Phase 3.6 — Residual Sonar triage (Sonar repos only)

Skip entirely when Phase 0 resolved Sonar to OFF. Once every sprint ticket is `Done` (check
`sprint_state.py`; never start this while anything is in flight), run the sonar-triage skill
once in ticket mode, with no `--pr` and no `--sprint`:

```
/sonar-triage <SONAR_KEY> --project <PROJECT> --repo <REPO_PATH>
```

What it does, what to hold it to, and how to treat test-file findings are in
[references/sonar-phases.md](references/sonar-phases.md), section "Phase 3.6".

## Phase 4 — Report

When no ticket is actionable, run `sprint_state.py` once more and report:
- tickets merged, with PR numbers
- anything left `To Do` / `In Progress` / blocked, and why
- cross-ticket impacts planners raised that the user should act on
- on a Sonar repo: hotspots triaged, tickets filed, and any flagged as false positives —
  those need a human to mark them "safe" in Sonar, since this workflow never does
- on a Sonar repo: the residual tickets Phase 3.6 filed, under which epic, and any decision
  it deferred — notably whether test-file findings should be excluded or refactored,
  which is the user's call and not this workflow's

Then **stop**. Do not start the next sprint.

## Known gotchas

- **PR title CI** rejects an uppercase subject or a trailing period (Conventional Commits).
  This is the single most common failure.
- **Gated tests** need a real database env var (`NESTOVA_TEST_DATABASE_URL` and the
  Nestorage equivalent). If Docker acts stale, `DOCKER_HOST` may need setting.
- **Story points** live on `customfield_10016` ("Story point estimate").
- Statuses in these projects are `To Do → Plan Created → In Progress → In Review → Done`,
  and transitions are direct — any status can move to any other.

## SonarQube mode (auto-detected)

A repo turns Sonar on by containing a `sonar-project.properties`; Phase 0 reads the result
from `sonar_state.py key`, and nothing is passed on the command line. The command table,
where Sonar touches the run, and the project-key rules are in
[references/sonar-phases.md](references/sonar-phases.md), section "SonarQube mode". Three
behaviours hold on every run:

- **Never auto-resolve a hotspot or an issue in Sonar.** The workflow files tickets and
  fixes code; marking something "safe" or "won't fix" is a human judgement.
- **Sonar analysis is asynchronous.** Re-check rather than treating the first answer as
  final; "no findings on this PR" may mean the PR has not been analysed yet.
- **A Sonar fix re-runs CI.** Step 10 pushes to the PR branch, so the green from step 8
  goes stale. Wait for CI again before merging.

## Maximum-freshness variant

To run each ticket in a brand-new process, drive implementation headlessly with Jira as the
state store; the loop is in [references/background.md](references/background.md).

## Files in this skill

- [scripts/sprint_state.py](scripts/sprint_state.py) — sprint table and verdict (Phase 0).
- [scripts/sonar_state.py](scripts/sonar_state.py) — Sonar detection, quality gate, issues, hotspots; also used by the `sonar-triage` skill in this plugin.
- [scripts/merge_readiness.py](scripts/merge_readiness.py) — one-pass "can this PR merge?" verdict.
- [scripts/ci_failure.py](scripts/ci_failure.py) — why a CI run is red.
- [scripts/job_history.py](scripts/job_history.py) — pass/fail record of a named CI job, to settle flake claims.
- [scripts/gh_common.py](scripts/gh_common.py) — shared `gh` helpers imported by the three scripts above; not called directly.
- [references/reply-and-resolve.md](references/reply-and-resolve.md) — how implementers reply to and resolve review threads.
- [references/sonar-phases.md](references/sonar-phases.md) — Phase 3.5 hotspot procedure and prompt, Phase 3.6, and the SonarQube mode details.
- [references/background.md](references/background.md) — why subagents and per-phase models; the headless per-ticket variant.
- [evals/test-prompts.md](evals/test-prompts.md) — three test prompts and the baseline without the skill.
