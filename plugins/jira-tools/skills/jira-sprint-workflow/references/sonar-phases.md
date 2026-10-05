# Sonar phases

Detail for the Sonar parts of the sprint workflow. SKILL.md holds the short version and the
rules that hold on every run; read this file when a Sonar repo reaches Phase 3.5 or 3.6, or
when you need the `sonar_state.py` command table.

## Contents

- Phase 3.5 — Security hotspot sweep (Sonar repos only)
- Phase 3.6 — Residual Sonar triage (Sonar repos only)
- SonarQube mode (auto-detected)

`sonar_state.py` lives in the skill's `scripts/` folder; SKILL.md gives its absolute path.
Commands below show it by name, and the Phase 3.5 prompt uses `<SONAR_STATE>`,
`<CREATE_ISSUE>` and `<UPDATE_ISSUE>` placeholders that the orchestrator fills in first.

## Phase 3.5 — Security hotspot sweep (Sonar repos only)

Skip this phase entirely when Phase 0 resolved Sonar to OFF. It runs **after every sprint
ticket is merged**,
and it loops until Sonar is clean.

Repeat until the hotspot count is zero:

1. List what is outstanding:
   ```sh
   python <SONAR_STATE> hotspots <SONAR_KEY>
   ```
   Zero hotspots → the sweep is done, go to Phase 4.

2. Spawn **one `opus` subagent** to triage and file tickets. Opus here is deliberate —
   this is the security-judgement step, and the source workflow escalated the model for
   exactly this. Send this prompt verbatim, filling <placeholders>:

   ```
   Triage SonarCloud security hotspots for <SONAR_KEY> and file Jira tickets.

   1. Run: python <SONAR_STATE> hotspots <SONAR_KEY> --json
   2. For each hotspot, read the flagged code and judge whether it is a real risk or a
      false positive. Say which, with a reason. Do not file tickets for false positives —
      note them for the user to mark "safe" in Sonar instead.
   3. For each REAL hotspot, create one Jira Task in <PROJECT>, labelled "security",
      using the house format (Description / Implementation Plan / Acceptance Criteria):
        python <CREATE_ISSUE> \
          -p <PROJECT> -t Task -s "<summary>" -d "<body>" --labels security
   4. Add each new ticket to the current sprint:
        POST /rest/agile/1.0/sprint/<SPRINT_ID>/issue  {"issues": ["<KEY>", ...]}
   5. Set story points (customfield_10016), then assign to Eric Fisher and move each to
      "Plan Created" in one call — these tickets skip the Phase 2 planner, so they must
      arrive work-ready and already assigned:
        python <UPDATE_ISSUE> <KEY> --status "Plan Created" --assignee "Eric Fisher"

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
