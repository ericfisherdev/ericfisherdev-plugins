---
name: jira-sprint-workflow
description: Run a full Jira sprint end to end — dependency audit, per-ticket implementation planning with story points, then sequential implement/review/merge — delegating every ticket to a fresh subagent so the main context never accumulates. Use when the user asks to "run the sprint", "work the sprint", "start the sprint workflow", or to work a sprint's tickets from To Do through Done.
---

# Jira Sprint Workflow

Drives an entire sprint from planning to merged. The orchestrator (you, in the main
session) never writes code, never reads a diff, and never reads a full ticket body.
Every ticket is handled by a **subagent with its own context window**, which is what
keeps a 20-ticket sprint from filling a 200k-token session.

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

## Why it is built this way

The source workflow says "clear your context after each merge." A session cannot clear
itself — `/clear` is user-invoked only, and no hook can trigger it. Subagents solve the
same problem natively: each starts with a fresh context and returns only a short summary.

It also said "SWITCH THE MODEL TO FABLE / SONNET". You do not switch anything — spawn
each subagent with a `model` override instead:

| Phase | Model | Why |
|---|---|---|
| Planning | `fable` | Research + plan writing, one agent per ticket, run in parallel |
| Implementation | `sonnet` | Code, CI, merge — one agent per ticket, strictly sequential |
| Security triage (Sonar repos) | `opus` | Judging real risk vs. false positive on Sonar hotspots |
| Orchestration | inherit | You stay on whatever the session is; you only route and report |

## Phase 0 — Preflight

Run the state helper. **This is the only way you read sprint state** — never page through
Jira JSON yourself:

```sh
python ~/.claude/skills/jira-sprint-workflow/scripts/sprint_state.py <PROJECT>
```

It prints one table plus a verdict: `planning complete`, external blockers, in-flight
tickets, and `next ticket`. Add `--sprint <id>` to target a specific sprint, `--json` if
you need to branch on fields.

Confirm before doing anything else:
- `gh auth status` is logged in

### The helper scripts

Five scripts back this workflow. Two are sprint-specific and live in
`~/.claude/skills/jira-sprint-workflow/scripts/`; the other three are repo-scoped, shared
with the board workflows, and live in `~/.claude/scripts/ci-helpers/` (also symlinked into
this skill's `scripts/`, so either path works). They exist for one reason: each collapses a
pile of API JSON into a few lines plus a verdict, so state can be read without loading
payloads into context. Use them instead of hand-rolling `gh` chains, in the orchestrator
**and** in subagent prompts.

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
  and looks like "nothing is required".
- **`job_history.py` settles the flake question with evidence, not reputation.** It counts a
  named job's pass/fail record per branch and distinguishes three shapes: interleaved
  passes and failures (a genuine flake), a branch that fails every time while others are
  clean (a real regression), and failures that are all newer than the passes (something
  landed and broke it, reported with the timestamp). Run it before accepting any "known
  flake" claim — see Known gotchas.

**Resolve Sonar once, here, and carry the answer through the run.** Whether the Sonar
steps happen is a property of the repo, not something the invoker has to remember:

```sh
python ~/.claude/skills/jira-sprint-workflow/scripts/sonar_state.py key <REPO_PATH>
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

Planner prompt template:

```
Plan Jira ticket <KEY> in project <PROJECT>. Do not write any implementation code.

Repository: <REPO_PATH>
Other tickets in this sprint (for cross-impact analysis only):
<KEY: summary list>

Steps:
1. Read the ticket: python <jira-tools>/skills/jira-issue/scripts/fetch_jira_issue.py <KEY>
2. Research every technology the ticket touches using context7 (resolve-library-id then
   query-docs). Prefer context7 over web search. Never guess an API — verify it.
3. Read the actual code the ticket will touch. Match existing patterns and conventions.
4. Judge whether this ticket forces changes to any sibling ticket above. Say so explicitly.
5. Rewrite the ticket's Implementation Plan section with a concrete, file-level plan.
   Keep the existing Description and Acceptance Criteria unless they are now wrong.
6. Estimate story points (Fibonacci: 1,2,3,5,8,13). 8+ means it should be split — say so.
7. Update the ticket:
   python <jira-tools>/skills/update-issue/scripts/update_jira_issue.py <KEY> \
     --description "<full markdown body>"
   Set points via the Jira REST API, field customfield_10016.
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
   python ~/.claude/scripts/ci-helpers/merge_readiness.py <N> --repo <REPO_PATH>
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
     pushing run the reply-and-resolve procedure — reply on each individual thread
     naming the commit that fixed it, or the reason plus follow-up if you are rebutting,
     then resolve it. Carry the PR through steps 11–14." Same 6-line return contract.
   - No activity → keep polling. After ~2 hours with no reviewer activity, report to the
     user and ask whether to merge under the standing authorization (CI green, no
     changes requested) or keep waiting.

Implementer prompt template:

```
Implement Jira ticket <KEY> end to end, in project <PROJECT>, repo <REPO_PATH>.

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
     python ~/.claude/scripts/ci-helpers/ci_failure.py --pr <N> --repo <REPO_PATH>
   It exits 0 on green and 1 on failure, so it doubles as the wait condition. Before
   you write off any failure as a known flake, prove it with:
     python ~/.claude/scripts/ci-helpers/job_history.py "<job name>" --repo <REPO_PATH>
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
      python ~/.claude/scripts/ci-helpers/merge_readiness.py <N> --repo <REPO_PATH>
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
      python ~/.claude/scripts/ci-helpers/merge_readiness.py <N> --repo <REPO_PATH>
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

Every thread you acted on gets its own reply on that thread. One summary comment on
the PR does not discharge this, and neither does resolving a thread silently — a
resolved thread with no reply reads as "ignored" to the reviewer and leaves no record
of the reasoning.

Order matters: push first, reply second, resolve third. Replying before the push
means quoting a commit hash that does not exist yet, and fabricating a hash is worse
than saying nothing.

 i. Push the fixes for this round, then read the real hashes:
      git -C <WORKTREE> log --oneline -n <count>
    Keep the mapping you built while fixing: thread -> the commit that addressed it.
ii. Reply to each thread, one call per thread, using the databaseId of the thread's
    FIRST comment (replies attach to the thread, not to the newest comment):
      gh api --method POST \
        repos/<owner>/<repo>/pulls/<N>/comments/<comment_database_id>/replies \
        -f body="<text>"
    - Fixed: name the commit and what changed —
      "Addressed in a1b2c3d — clamp ageBoost to non-negative so future-dated items
      cannot lower the score." Do not just write "fixed" or "done".
    - Rebutted: give the reason, concretely, from the code you actually read —
      which premise is wrong, or which existing guard already covers it, with the
      file:line that shows it. Then state the follow-up: none needed, a Jira key you
      filed, or what you deferred and why. A rebuttal with no follow-up line is
      incomplete when the reviewer's underlying concern is real but out of scope.
    - Before posting, check the thread for an existing reply of yours. Never
      double-reply on a re-review round.
iii. Resolve each thread you replied to, fixed AND rebutted alike, via GraphQL using
    the thread's node id (not the comment id):
      gh api graphql -f query='mutation {
        resolveReviewThread(input: { threadId: "<thread_node_id>" }) {
          thread { isResolved }
        }
      }'
    Resolving rebuttals is deliberate here and diverges from the address-pr-reviews
    default: step 12 cannot merge over an unresolved thread, so an unresolved
    rebuttal stalls the sprint. The reply carries the reasoning; the reviewer can
    reopen the thread if they disagree, and a reopened thread blocks the merge again.
iv. A review comment with no thread — a top-level PR comment or a review body — has
    nothing to resolve. Reply to it in place instead
    (gh pr comment <N> --body "..."), same content rules.
 v. Re-read the thread list after this pass. Zero unresolved actionable threads is
    the step 12 gate; if any remain, you missed one — go back to (ii).

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
ticket is merged**,
and it loops until Sonar is clean.

Repeat until the hotspot count is zero:

1. List what is outstanding:
   ```sh
   python ~/.claude/skills/jira-sprint-workflow/scripts/sonar_state.py hotspots <SONAR_KEY>
   ```
   Zero hotspots → the sweep is done, go to Phase 4.

2. Spawn **one `opus` subagent** to triage and file tickets. Opus here is deliberate —
   this is the security-judgement step, and the source workflow escalated the model for
   exactly this. Its prompt:

   ```
   Triage SonarCloud security hotspots for <SONAR_KEY> and file Jira tickets.

   1. Run: sonar_state.py hotspots <SONAR_KEY> --json
   2. For each hotspot, read the flagged code and judge whether it is a real risk or a
      false positive. Say which, with a reason. Do not file tickets for false positives —
      note them for the user to mark "safe" in Sonar instead.
   3. For each REAL hotspot, create one Jira Task in <PROJECT>, labelled "security",
      using the house format (Description / Implementation Plan / Acceptance Criteria):
        python <jira-tools>/skills/create-issue/scripts/create_jira_issue.py \
          -p <PROJECT> -t Task -s "<summary>" -d "<body>" --labels security
   4. Add each new ticket to the current sprint:
        POST /rest/agile/1.0/sprint/<SPRINT_ID>/issue  {"issues": ["<KEY>", ...]}
   5. Set story points (customfield_10016), then assign to Eric Fisher and move each to
      "Plan Created" in one call — these tickets skip the Phase 2 planner, so they must
      arrive work-ready and already assigned:
        ... update_jira_issue.py <KEY> --status "Plan Created" --assignee "Eric Fisher"

   Return AT MOST 8 lines: one per hotspot — key, real-or-false-positive, ticket created.
   ```

3. Run the **Phase 3 loop** over the newly created security tickets, exactly as for any
   other ticket: sequential, one Sonnet subagent each, same CI and merge gates.

4. Go back to step 1 and re-check. Sonar rescans on merge, so the count should fall.
   If it does not change after a full pass, stop and report rather than looping forever.

## Phase 3.6 — Residual Sonar triage (Sonar repos only)

Skip entirely when Phase 0 resolved Sonar to OFF. Runs **once every sprint ticket is `Done`** — check
`sprint_state.py` and do not start this while anything is still in flight, because a
merge still to come changes what "remaining" means.

Per-PR triage (step 10) only ever cleaned up what each PR introduced. What is left is the
pre-existing debt on `main`: findings that predate the sprint, plus anything the per-PR
passes deliberately declined to fix. This phase turns that residue into tickets so it is
tracked rather than silently carried.

Run the sonar-triage skill in **ticket mode** — no `--pr`:

```
/sonar-triage <SONAR_KEY> --project <PROJECT> --repo <REPO_PATH>
```

What that skill does, and what you therefore do not need to do here: it groups findings by
rule, skips any rule already filed (matching on its sentinel, so re-running is safe),
resolves or creates the `SonarQube` epic, files one Task per group in the house format,
and sets points. It never resolves anything in Sonar.

Two things to hold it to:

- **Do not add these tickets to the finished sprint.** Omit `--sprint`; they belong in the
  backlog for a later sprint. Closing a sprint by stuffing fresh work into it defeats the
  point of the report in Phase 4.
- **Findings in test files need a decision, not a reflex fix.** The skill will surface
  them rather than auto-refactoring; carry that question up to the user in the Phase 4
  report instead of answering it on their behalf.

Run it once. Unlike Phase 3.5 this does not loop: nothing here is being merged, so the
finding count will not move.

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

## Orchestrator context rules

These are the point of the whole skill. Violating them defeats it.

- **Never** read ticket descriptions, source files, diffs, PR bodies, or CI logs in the
  main session. Subagents do that in their own context.
- Your entire working memory is the ledger: one line per ticket.
- Cap every subagent's return at ~6 lines and say so in the prompt.
- If you find yourself with a large tool result in context, that is a bug in how you
  delegated — push that work into a subagent next time.

## Standing authorizations

For sprint-workflow runs the user has pre-authorized, so do not stop to ask each time:
- taking a PR out of draft once CI passes
- merging once every required check is green on the PR's current head
- replying to review threads on the sprint's own PRs, and resolving the threads you
  replied to — including ones you rebutted

Everything else consequential — force-pushing, deleting branches other than the merged
feature branch, editing tickets outside the sprint — still needs a check-in.

## Known gotchas

- **PR title CI** rejects an uppercase subject or a trailing period (Conventional Commits).
  This is the single most common failure.
- **"Known flake" is a claim, not a fact.** A documented flake in a repo's CLAUDE.md makes
  the flake label the default assumption, which is exactly what makes it dangerous: a real
  regression in the same job gets waved through. Settle it with evidence before merging:
  `job_history.py "<job name>"` prints the job's pass/fail record per branch. A flake fails
  intermittently on the same branch; a regression fails every run on one branch while
  others stay clean, or fails only after a given timestamp. Failing 4-of-4 on your branch
  while five sibling branches pass is not a flake.
- **Never conclude "nothing is required on main" from `required_status_checks` alone.**
  A branch can require approving reviews with no required checks at all, in which case
  that field reads as null and the PR still cannot merge. `merge_readiness.py <PR>` reads
  protection and rulesets together; a brief built on a partial read gets passed into
  subagent prompts and costs them a denied merge attempt.
- **Subagents must not end a turn to wait.** No notification arrives when CI finishes, so
  a subagent that hands control back "until the build completes" simply stalls until the
  orchestrator nudges it. Waiting belongs inside a turn — a blocking watch, `gh pr checks
  --watch`, or `ci_failure.py` as the exit-code condition.
- **Gated tests** need a real database env var (`NESTOVA_TEST_DATABASE_URL` and the
  Nestorage equivalent). If Docker acts stale, `DOCKER_HOST` may need setting.
- **Story points** live on `customfield_10016` ("Story point estimate").
- Statuses in these projects are `To Do → Plan Created → In Progress → In Review → Done`,
  and transitions are direct — any status can move to any other.
- **Assignment invariant.** Every ticket is assigned to the sprint owner the moment it
  leaves `To Do` (at `Plan Created`), and **no ticket may reach `Done` unassigned** — the
  Done transition re-asserts the assignee as a backstop. The owner here is **Eric Fisher**
  (`update_jira_issue.py --assignee` does a partial, case-insensitive match on Jira display
  name); change that string if the sprint owner ever changes. `--assignee` and `--status`
  can be passed in one call — the script sets fields before it transitions.

## SonarQube mode (auto-detected)

**A repo turns Sonar on by containing a `sonar-project.properties`.** Nothing is passed on
the command line and nothing is inferred from the repo name: Phase 0 runs
`sonar_state.py key <REPO_PATH>` and the exit status decides. `nestcore` has the file, so
its runs include the Sonar steps; `nestorage` and `nestova` do not, so theirs skip them
silently. When a repo gains a Sonar project, adding the file is the entire change — no
skill edit, no flag to remember.

The project key comes from that file's `sonar.projectKey`. It is *not* the repo name — it
looks like `ericfisherdev_nestcore` or `LiteRec_literec-admin-php` — so never construct
one; the whole point of reading the file is that guessing is unnecessary.

The instance is **SonarCloud** (`https://sonarcloud.io`), authenticated with a **Bearer**
token from `SONARQUBE_TOKEN`.

Verified commands, all wrapped by `scripts/sonar_state.py` so you never handle the JSON:

| Need | Command | Needs credentials |
|---|---|---|
| Is this repo analysed, and under what key | `sonar_state.py key <REPO_PATH>` | no |
| Gate on a PR | `sonar_state.py gate <KEY> --pr <N>` | yes |
| Gate on a branch | `sonar_state.py gate <KEY> [--branch NAME]` | yes |
| Issues on a PR or branch | `sonar_state.py issues <KEY> [--pr N] [--branch NAME]` | yes |
| Outstanding hotspots | `sonar_state.py hotspots <KEY>` | yes |

Where Sonar touches the run — three distinct points, doing three different jobs:

| When | Phase | Scope | Files tickets? |
|---|---|---|---|
| Per PR, after CI green and out of draft | step 10 | only what that PR **added** | no — fixes in place |
| After every ticket merged | 3.5 | security hotspots | yes, into this sprint |
| After every ticket is `Done` | 3.6 | everything **remaining** on `main` | yes, into the backlog |

Steps 10 and 3.6 are both the `sonar-triage` skill; the presence of `--pr` is what decides
whether it fixes code or files tickets. Keeping the two scopes apart is the point: a
feature PR should carry its own mess and nobody else's.

Three Sonar behaviours are deliberate:
- **Never auto-resolve a hotspot or an issue in Sonar.** The workflow files tickets and
  fixes code; marking something "safe" or "won't fix" is a human judgement.
- **Sonar analysis is asynchronous.** After a push, the gate may briefly report the
  previous run. Re-check rather than treating the first answer as final. In particular,
  "no findings on this PR" may mean the PR has not been analysed yet — check the PR's
  gate before believing it.
- **A Sonar fix re-runs CI.** Step 10 pushes to the PR branch, so the green from step 8
  goes stale. Wait for CI again before merging.

## Maximum-freshness variant

Subagents give a fresh context but share the session's process. For a genuinely new
process per ticket — the closest thing to "clear context between tasks" — drive the
implementation phase headlessly, using **Jira as the state store** so each invocation
rediscovers where it is:

```sh
while :; do
  KEY=$(python ~/.claude/skills/jira-sprint-workflow/scripts/sprint_state.py NSTR --json \
        | python -c 'import json,sys; print(json.load(sys.stdin)["next_ticket"] or "")')
  [ -z "$KEY" ] && break
  claude -p "Use the jira-sprint-workflow skill's implementer procedure for $KEY only."
done
```

Each `claude -p` is a brand-new session. Slower and harder to supervise, but nothing
carries over between tickets at all.
