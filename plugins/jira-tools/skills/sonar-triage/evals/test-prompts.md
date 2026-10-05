# Test prompts for sonar-triage

Run each prompt in a fresh session with the skill on and again with it off. Compare against the expected outcome.

## Prompt 1: ticket mode

> Create jira tickets from sonarqube for ericfisherdev_nestcore, file them in project NSTR.

Expected with skill: fetches findings through `sonar_state.py issues`, reports a grouping table (rule, count, files), searches for already-filed sonar tickets, resolves or creates the `SonarQube` epic before any task, then files one Task per rule group with Description / Implementation Plan / Acceptance Criteria and a fenced sentinel. Sets points and epic parent, runs the key-diff, and reports one line per group. No code touched and nothing resolved in Sonar.

Baseline without skill: files one ticket per finding or one ticket for everything, no dedupe, no epic, no sentinel, wiki markup in the bodies, and may offer to mark findings as won't-fix.

## Prompt 2: PR-fix mode

> Fix the sonar issues on PR 42 in ~/dev/nestcore, Sonar key is ericfisherdev_nestcore.

Expected with skill: fetches findings scoped to PR 42, works on the PR's existing branch (no second PR), delegates the edits to one subagent, runs the repo gates until green, commits with a specific conventional subject, pushes, and stops without merging or taking the PR out of draft. Creates no Jira issues. Notes that the quality gate re-check is pending if the analysis has not re-run.

Baseline without skill: opens a new branch or PR, fixes findings one by one without grouping, may mark issues resolved in Sonar, and reports the gate as passing from a stale analysis.

## Prompt 3: no-findings case

> Triage the sonar issues for LiteRec_literec-admin-php into project LRA.

Expected with skill: the preflight fetch returns zero findings, so it says so and stops. No grouping report, no epic, no tickets. If the repo had no `sonar-project.properties` it would report that nothing is analysed and stop as well.

Baseline without skill: invents work, such as a generic "fix sonar issues" ticket or a code-quality sweep, or builds the Sonar API call by hand.
