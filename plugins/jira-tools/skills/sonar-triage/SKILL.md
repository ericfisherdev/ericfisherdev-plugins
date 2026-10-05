---
name: sonar-triage
description: Turn open SonarQube/SonarCloud issues into Jira tickets, or — when a PR number is given — fix those issues directly on that PR and file nothing. Use when the user asks to "create jira tickets from sonarqube", "file the sonar issues", "triage sonar issues", or "fix the sonar issues on PR N".
---

# Sonar Triage

Reads open SonarQube issues and does one of two things with them. **The presence of
`--pr` is the only thing that decides which.**

| Invocation | Mode | Effect |
|---|---|---|
| `/sonar-triage <SONAR_KEY> --project <JIRA_KEY>` | **Ticket** | groups findings, files Jira Tasks, touches no code |
| `/sonar-triage <SONAR_KEY> --pr <N>` | **Fix** | fixes the findings on that PR, creates **no** Jira issues |

Passing both is a mistake, not a combination: `--pr` wins and Jira is left alone. Say so
rather than silently filing tickets as well.

## Invocation

```
/sonar-triage <SONAR_KEY> [--project <JIRA_KEY>] [--pr <N>] [--repo <path>]
              [--sprint <id>] [--epic <name>]
```

- `SONAR_KEY` — Sonar project key (e.g. `ericfisherdev_nestcore`). **Not** the repo name.
  **Optional when `--repo` is given**: resolve it from the repo instead of asking, with
  `sonar_state.py key <REPO_PATH>` (exit 0 prints the key, exit 1 means the repo has no
  `sonar-project.properties` and there is nothing to triage — say so and stop). Never
  construct a key by hand.
- `--project` — Jira project key for ticket mode (`NSTR`, `NES`, …)
- `--pr` — GitHub PR number. Switches to fix mode.
- `--repo` — repo path; needed in fix mode, and for reading code in ticket mode
- `--sprint` — sprint id to add new tickets to (ticket mode only; otherwise backlog)
- `--epic` — epic to collect the tickets under; defaults to `SonarQube`. Reused if it
  already exists, created if it does not (ticket mode only — see A3)

## Phase 0 — Preflight (both modes)

0. Resolve the Sonar key if it was not passed explicitly:

   ```sh
   python ~/.claude/skills/jira-sprint-workflow/scripts/sonar_state.py key <REPO_PATH>
   ```

   Exit 1 means the repo carries no `sonar-project.properties` — it is not analysed, so
   there is nothing to triage. Report that and stop; it is a normal answer, not a failure.
1. `SONARQUBE_URL` and `SONARQUBE_TOKEN` are set. If not, stop — do not fall back to
   scraping the web UI.
2. Fetch the findings. **This is the only way you read Sonar state**; never hand-roll the
   API:

   ```sh
   python ~/.claude/skills/jira-sprint-workflow/scripts/sonar_state.py \
     issues <SONAR_KEY> [--pr <N>] --json
   ```

   Each finding carries `key`, `rule`, `severity`, `type`, `component`, `line`, `effort`,
   `message`. `key` identifies the exact finding; `rule` identifies the check.
3. Zero findings → say so and stop. Do not invent work.

**Sonar analysis is asynchronous.** Right after a push, the API still answers from the
previous run. If the findings look stale, re-check rather than treating the first answer
as final — and in fix mode, never conclude "already fixed" from a single query.

## Phase 1 — Group before doing anything

Never treat findings one-per-unit-of-work. Group by `rule`, then split a group only where
the fix genuinely differs (e.g. same rule, but one instance is in generated code).

Report the grouping before acting:

```
go:S3776  x11  7 files (5 test files)   cognitive complexity
go:S1186  x2   2 files                  empty function body
```

### Judge test-file findings separately — do not reflexively "fix" them

A large share of Go findings land in `_test.go` files, and table-driven tests trip
complexity rules by design. Splitting a readable table test into helpers to satisfy a
metric usually makes the suite worse. For any group that is mostly test files, present
the options and let the user choose:

- **exclude** — add the path to `sonar.exclusions` / `sonar.issue.ignore` in
  `sonar-project.properties` (a config change, often the right answer)
- **refactor** — genuinely worth it when the test is hard to follow
- **leave** — accept the finding

Never silently pick one. This is the single most common way this command produces
unwanted churn.

### Never resolve anything in Sonar

Marking a finding won't-fix, false-positive or safe is a human judgement. This command
files tickets and changes code; it never mutates issue state in Sonar. Surface candidates
for the user to mark by hand instead.

---

## Mode A — Ticket mode (no `--pr`)

One Jira Task **per group**, not per finding.

### A1. Skip what is already filed

Before creating anything, search for an existing ticket for that rule:

```sh
python <jira-tools>/skills/search-issues/scripts/search_issues.py \
  --jql 'project = <JIRA_KEY> AND labels = sonar AND statusCategory != Done' \
  --fields summary,description --format json
```

Match on the sentinel below. A rule that already has an open ticket is **skipped**, and
reported as skipped — re-running this command must not litter the backlog with duplicates.

### A2. Sentinel

Every ticket description ends with a machine-readable block, so a later run can tell what
was already filed without parsing prose. **It must be a fenced code block** — that is not
cosmetic, see below:

    sonar-triage metadata (do not edit):

    ```
    sonar-rule: go:S3776
    sonar-project: ericfisherdev_nestcore
    sonar-keys: AZ-Iu4MkCOaOXasPTcIW,AZ-Iu4MkCOaOXasPTcIX
    ```

Keep it last, keep the key list complete, and never reformat it — it is parsed, not read.

**Why fenced, and not an HTML comment or plain text.** Descriptions are converted
markdown → ADF on the way in, and that conversion is destructive in two ways. An HTML
comment vanishes entirely. Plain text survives only until the first underscore, because
the converter reads `_` as emphasis: `ericfisherdev_nestcore` was silently split into two
text nodes, and every Sonar key containing an underscore (e.g. `AZ-IzLtwlM3PEnpio_yA`)
was truncated at it. Both failures are silent — the ticket looks fine and the dedupe
simply stops working. Inside a fence, emphasis is not parsed and the block round-trips
byte for byte.

**Always build the key list from the fetched JSON, never by hand.** Hand-typing a key
into a sentinel is how a finding ends up filed under the wrong rule while its real
finding stays unfiled — and because the totals still add up, nothing looks wrong. After
filing, verify: read every sentinel back and assert the union of keys equals the set of
findings, with no duplicates.

### A3. Resolve the epic — find it, or create it

Every ticket this command files belongs to a single epic, so Sonar work stays collected
instead of scattered through the backlog. Default name: **`SonarQube`** (override with
`--epic`). Resolve it **before** creating any task, so a failure here does not strand
orphan tickets.

Look for it first:

```sh
python <jira-tools>/skills/search-issues/scripts/search_issues.py \
  --jql 'project = <JIRA_KEY> AND issuetype = Epic AND summary ~ "SonarQube" AND statusCategory != Done' \
  --format compact
```

`~` is a fuzzy match, so confirm the summary is actually the epic name before reusing it —
do not adopt an unrelated epic that merely contains the word. More than one match is a
stop-and-ask, not a pick-the-first.

If none exists, create it in the house Epic format — **Description / Acceptance Criteria**,
no Implementation Plan:

```sh
python <jira-tools>/skills/create-issue/scripts/create_jira_issue.py \
  -p <JIRA_KEY> -t Epic -s "SonarQube" --labels sonar,tech-debt -d "<body>"
```

The Description should say which Sonar project is analysed, where it is scanned from, and
what the analysis currently reports. The Acceptance Criteria should be the standing bar
for the epic, not a snapshot: every finding either resolved or recorded as a deliberate
exception, a standing policy agreed for rules that fire against test code, the quality
gate passing, and `make test` / `make lint` staying green throughout.

Never create a second epic when one already exists — that is the failure this step exists
to prevent.

### A4. Ticket body — house format

**Write the body in Markdown, never Jira wiki markup.** `create_jira_issue.py` runs the
text through a markdown → ADF converter, so wiki syntax does not render, it survives as
literal characters:

| Want | Write | Never write |
|---|---|---|
| Section heading | `## Description` | `h2. Description`, `h. Description` |
| Numbered step | `1. do the thing` | `# do the thing` |
| Bullet | `- the thing` | `* the thing` at line start is fine, `#` is not |

The `#` mistake is the nasty one: in wiki markup `#` starts a numbered list, but the
converter reads `#{1,6}` as a **heading**, so every step of an Implementation Plan renders
as a giant H1. It looks obviously wrong in the UI and completely fine in the source.

**Wrap every identifier containing an underscore in backticks.** The converter's inline
pattern tries `_italic_` *before* `` `code` ``, so two bare underscores anywhere in a
paragraph turn the text between them into emphasis and eat the underscores. A body
mentioning `config_test.go` and `db_test.go` silently loses both. Backticks prevent it,
because the opening backtick is reached before the underscores inside it.

Do not combine bold with inline code (`**`code`**`) — that yields a bare `INVALID_INPUT`.

Fill the sections from the findings:

- **Description** — what the rule flags and why it matters here. Name the affected files
  and counts. Do not paste all N messages; they repeat.
- **Implementation Plan** — the concrete fix, file by file, with line numbers. Read the
  actual code first; a plan written from the Sonar message alone is a guess.
- **Acceptance Criteria** — testable. Always include: the rule reports zero open findings
  for these paths on the next analysis, and `make test` / `make lint` stay green.

Create it:

```sh
python <jira-tools>/skills/create-issue/scripts/create_jira_issue.py \
  -p <JIRA_KEY> -t Task -s "<summary>" -d "<body>" --labels sonar,tech-debt
```

Summary style follows the house rule: name the specific thing, lowercase-ish prose, no
trailing period. `reduce cognitive complexity in the config and db test suites` — not
`fix sonar issues`.

### A5. Points, epic, and placement

Estimate story points from the aggregated `effort` (Fibonacci: 1,2,3,5,8,13) and set
`customfield_10016`. Attach every task to the epic from A3 in the same pass — epic
membership is the `parent` field, not a link type:

```sh
curl -X PUT -u "$JIRA_EMAIL:$JIRA_API_TOKEN" -H "Content-Type: application/json" \
  "$JIRA_BASE_URL/rest/api/3/issue/<TASK>" \
  -d '{"fields":{"parent":{"key":"<EPIC>"}}}'
```

Both of these are separate calls: `create_jira_issue.py` sets neither points nor parent.
A task created but never re-visited is left pointless and orphaned, which is exactly the
state this step exists to prevent — so verify both landed before reporting success.

With `--sprint`, add the ticket to that sprint:

```
POST /rest/agile/1.0/sprint/<SPRINT_ID>/issue  {"issues": ["<KEY>", ...]}
```

Without it, leave the ticket in the backlog — do not guess a sprint.

**Assignment.** A ticket left in the backlog stays `To Do` and unassigned; the sprint
workflow assigns it when it moves it to `Plan Created`. But a ticket added straight to a
sprint with `--sprint` skips that planner, so it must arrive assigned and work-ready —
the same rule Phase 3.5 of `jira-sprint-workflow` follows for security tickets. Pass
`--assignee "Eric Fisher"` in that case, and move it to `Plan Created` once it has points.

### A6. Report

One line per group: rule, count, ticket key or `skipped (already filed as X)`, plus
anything you flagged for a human decision.

---

## Mode B — Fix mode (`--pr <N>` given)

**Creates nothing in Jira.** Fixes the findings on the PR and pushes.

### B1. Scope the findings to the PR

```sh
python ~/.claude/skills/jira-sprint-workflow/scripts/sonar_state.py \
  issues <SONAR_KEY> --pr <N> --json
```

If this returns nothing, distinguish the two causes before reporting success:

- Sonar has not analysed the PR yet (no analysis → no findings), or
- the PR genuinely has no findings.

Check the PR's own gate (`sonar_state.py gate <SONAR_KEY> --pr <N>`). An analysis that
has never run is not a clean bill of health.

### B2. Work on the PR's branch, not a new one

Fixes belong on the branch the PR already has:

```sh
gh pr view <N> --repo <owner/repo> --json headRefName --jq .headRefName
git -C <REPO_PATH> worktree add <slug> <branch>     # reuse if one exists
git -C <REPO_PATH>/<slug> pull --ff-only            # another agent may have pushed
```

Never open a second PR for the fixes.

### B3. Fix, then prove it

Delegate the edits to **one subagent** so the findings and diffs stay out of the main
context. Its brief:

- Fix each finding on its merits. Match surrounding code and the repo's conventions.
- A finding whose honest answer is "this is a false positive" gets **no code change** —
  report it for a human to mark in Sonar.
- Run the repo's own gates until green (`make fmt`, `make lint`, `make test`, or the
  repo equivalent). A fix that satisfies Sonar and breaks the build is not a fix.
- Return at most 6 lines: rule, files touched, gates green y/n, anything deliberately
  not fixed and why.

### B4. Commit and push

Conventional Commits. Subject lowercase, no trailing period, naming the specific change:

- Good: `refactor: extract table-driven cases to cut config_test complexity`
- Bad: `fix: address sonar issues`

Push to the PR's branch. Then **stop**:

- do **not** merge
- do **not** take the PR out of draft
- do **not** mark anything resolved in Sonar

Re-checking the gate immediately after the push will often still show the previous
analysis. Say that the re-check is pending rather than reporting a pass or fail that the
server has not actually produced yet.

### B5. Report

Rules fixed, files touched, gate state (with the async caveat if it has not re-run), and
anything left deliberately unfixed.

---

## Gotchas

- **`--pr` and `--project` together**: `--pr` wins, Jira untouched. Say so explicitly.
- **A Sonar key is not a repo name.** `ericfisherdev_nestcore`, `LiteRec_literec-admin-php`.
  Ask; do not construct.
- **`sonar_state.py issues` needs `componentKeys`, not `components`** — an old bug, fixed;
  if it 400s again, that parameter is the first place to look.
- **Story points** live on `customfield_10016`.
- **Jira descriptions reject** bold-wrapped inline code and indented code fences with a
  bare `INVALID_INPUT`. Separately, and more insidiously, the markdown → ADF conversion
  eats `_` as emphasis — which corrupts Sonar issue keys. Keep the sentinel fenced.
- **Descriptions are Markdown, not wiki markup.** `h. Heading` renders as literal text and
  `#` renders as an H1 rather than a numbered list. After writing any description, read
  the ADF back and assert: no heading with `level: 1`, no literal `h. ` in the text, and
  zero `em` marks. All three are silent failures that look correct in the source.
- **Story points are a separate call.** `create_jira_issue.py` has no points flag; set
  `customfield_10016` with a follow-up `PUT /rest/api/3/issue/<KEY>`.
- **Epic membership is the `parent` field**, set the same way:
  `PUT /rest/api/3/issue/<KEY>` with `{"fields":{"parent":{"key":"<EPIC>"}}}`.
- **Effort is per finding.** Sum a group before converting to points.
