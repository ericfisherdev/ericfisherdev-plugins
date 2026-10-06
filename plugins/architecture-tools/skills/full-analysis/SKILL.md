---
name: full-analysis
description: Runs a complete 33-section architecture, behavioral (git X-Ray), and forensic analysis of a repository or one subdirectory of a mono-repo and writes each section as its own numbered markdown file under .analysis/full/ with an index. Use when the user asks for a "full analysis", "full architecture analysis", "complete project analysis", "architecture documentation", "document this codebase end to end", or wants every analysis (API, database, auth, security, hotspots, churn, bus factor, code age) in one run.
argument-hint: '[subdirectory]'
---

# Full Analysis

Act as a senior software architect. Run all 33 analyses in order and write each result to its own file. Each analysis prompt lives in `references/`; this file only sequences them.

## Rules that hold every time

- **One section at a time.** Read the section's reference file, run it, write its output file, then go to the next. Do not read all references up front.
- **Write each file straight after its analysis.** A stopped run must leave every finished section on disk.
- **Never skip a section.** If a feature does not exist (no events, no ML), still write the file and state what was checked and that nothing was found.
- **One failure does not stop the run.** Record the error in that section's file and continue.
- **Ignore `arch-docs`, `vendor`, `node_modules`, `.git`, `var`, and `.analysis`** in every section, including in `git log` pathspecs (`':(top,exclude).analysis'`, so the exclusion works from any directory). The references repeat part of this; it holds even where one does not. `.analysis` holds this skill's own earlier output and must never count as project content.
- **Time windows use each reference's default.** The references mention a `--since` window; this skill takes no such argument, so use the default each file states.
- **Delete only this skill's own output.** Before a run, remove `NN-*.md` and `00-index.md` in the target output directory, nothing else.

## Contents

- Rules that hold every time
- Needs
- Usage
- Workflow (Steps 1 to 6, with checklist)
- Section table
- Output file format
- Index file format
- Completion report
- Reference files

## Needs

- `git` with history available. Sections 17 to 33 read `git log`. A shallow clone gives thin results; say so in those files.
- `gh` CLI, authenticated (`gh auth status`), for section 21 only. Without it, section 21 is skipped and says why.
- Standard shell tools: `awk`, `sort`, `uniq`, `wc`, `find`, `grep`.
- Run from any directory inside the repository; the skill resolves the repository root itself.

## Usage

```
/full-analysis                    # whole repository
/full-analysis packages/api       # one subdirectory of a mono-repo
/full-analysis apps/frontend      # nested path
```

## Workflow

Copy this checklist and track progress with it (one line per section is tracked in Step 4):

- [ ] Step 1: Check prerequisites
- [ ] Step 2: Set scope and names
- [ ] Step 3: Prepare the output directory
- [ ] Step 4: Run the 33 sections in order
- [ ] Step 5: Write the index
- [ ] Step 6: Report

### Step 1: Check prerequisites

Run `git rev-parse --is-inside-work-tree` and `git log -1`. If either fails, stop before touching any file: the behavioral sections cannot run.

Set `ROOT` to the output of `git rev-parse --show-toplevel`, then change into `ROOT` (in its own shell call) and stay there for the whole run. Shell variables do not persist between calls, so derive `ROOT` and `OUT_DIR` again in each call or write the literal paths. Every path below is under `ROOT`, and every `git` and `find` command in the references then runs from the repository root.

Run `gh auth status`. Record the result; it decides section 21 in Step 4.

If a git check fails, report which one and stop; the user fixes it and runs the skill again. A `gh` failure does not stop the run: record it, and section 21 is skipped in Step 4.

### Step 2: Set scope and names

If an argument was given, it is the subdirectory to analyze, relative to `ROOT`:
- Normalize it: strip a leading `./` and trailing `/`. Treat `.` as no argument. Stop and tell the user if it is an absolute path or contains `..`.
- `SUBDIR` = the normalized path (for example `apps/frontend`).
- `SUBDIR_SLUG` = `SUBDIR` with `/` replaced by `.` (for example `apps.frontend`). Two different paths can give the same slug (`a/b.c` and `a.b/c`); a later run then overwrites the earlier one. Mention this only if it happens.
- Confirm `ROOT/SUBDIR` exists. If it does not, stop and tell the user; do not guess another path.
- Scope every command and file search in every section to that subdirectory only.

If no argument was given, the scope is the whole repository.

`REPO_NAME`, first match wins:
1. The repo name from `git remote get-url origin` (last path part, without `.git`). Do not read `.git/config` directly; in a worktree `.git` is a file.
2. `name` in root `package.json`
3. `name` in root `pyproject.toml`
4. `name` in root `composer.json`
5. `name` in root `Cargo.toml`
6. `artifactId` in root `pom.xml`
7. The name of `ROOT` (`basename "$ROOT"`)

`CURRENT_DATE` is the output of `date +%F`.

### Step 3: Prepare the output directory

`OUT_DIR` is `$ROOT/.analysis/full` for a whole-repo run, or `$ROOT/.analysis/full/$SUBDIR_SLUG` for a subdirectory run.

```bash
mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR"/[0-9][0-9]-*.md
```

Previous output of this skill is overwritten by design. Do not remove any other file.

### Step 4: Run the 33 sections in order

Use the section table below. For each section, in order:

1. Read the section's reference file in full.
2. Run the analysis exactly as that file describes, scoped per Step 2.
3. Write the result to `$OUT_DIR/<output file>` using the output file format below.
4. Mark the section done in the checklist, then start the next.

Section 21 needs `gh`. If `gh auth status` failed in Step 1, do not run it. Write the file with the title and one line saying it was skipped because `gh` was not authenticated.

If a section fails partway, write what finished plus the error text, mark it `failed` for the report, and continue. Do not retry more than once.

### Step 5: Write the index

After section 33, write `$OUT_DIR/00-index.md` using the index file format below.

Then list `$OUT_DIR`. If a numbered file is missing for a section not marked `skipped` or `failed`, go back to Step 4 for that section.

### Step 6: Report

Give the completion report below. Keep it short.

## Section table

Read the reference only when you reach that section. All paths are inside this skill folder.

### Architecture and structure (sections 1 to 16)

| # | Section | Reference | Output file |
|---|---------|-----------|-------------|
| 1 | Project Overview | [create-overview](references/create-overview.md) | `01-project-overview.md` |
| 2 | HTTP API Documentation | [document-api](references/document-api.md) | `02-api-documentation.md` |
| 3 | Database Architecture | [analyze-database](references/analyze-database.md) | `03-database-architecture.md` |
| 4 | Core Entities & Domain Models | [analyze-entities](references/analyze-entities.md) | `04-entities.md` |
| 5 | Authentication | [analyze-authentication](references/analyze-authentication.md) | `05-authentication.md` |
| 6 | Authorization | [analyze-authorization](references/analyze-authorization.md) | `06-authorization.md` |
| 7 | External Dependencies | [analyze-dependencies](references/analyze-dependencies.md) | `07-dependencies.md` |
| 8 | Service Dependencies | [analyze-service-dependencies](references/analyze-service-dependencies.md) | `08-service-dependencies.md` |
| 9 | Event Architecture | [analyze-events](references/analyze-events.md) | `09-events.md` |
| 10 | Deployment & CI/CD | [analyze-deployment](references/analyze-deployment.md) | `10-deployment.md` |
| 11 | Monitoring & Observability | [analyze-monitoring](references/analyze-monitoring.md) | `11-monitoring.md` |
| 12 | Feature Flags | [analyze-feature-flags](references/analyze-feature-flags.md) | `12-feature-flags.md` |
| 13 | ML/AI Services | [analyze-ml-services](references/analyze-ml-services.md) | `13-ml-services.md` |
| 14 | Data Privacy & Compliance | [analyze-data-mapping](references/analyze-data-mapping.md) | `14-data-privacy.md` |
| 15 | Security Assessment | [security-audit](references/security-audit.md) | `15-security-assessment.md` |
| 16 | LLM Security Assessment | [llm-security-audit](references/llm-security-audit.md) | `16-llm-security.md` |

### Behavioral code analysis, X-Rays (sections 17 to 23)

| # | Section | Reference | Output file |
|---|---------|-----------|-------------|
| 17 | Code Hotspots | [analyze-hotspots](references/analyze-hotspots.md) | `17-hotspots.md` |
| 18 | Change Coupling | [analyze-change-coupling](references/analyze-change-coupling.md) | `18-change-coupling.md` |
| 19 | Knowledge Map & Bus Factor | [analyze-knowledge-map](references/analyze-knowledge-map.md) | `19-knowledge-map.md` |
| 20 | Code Churn | [analyze-code-churn](references/analyze-code-churn.md) | `20-code-churn.md` |
| 21 | PR Complexity (needs `gh`) | [analyze-pr-complexity](references/analyze-pr-complexity.md) | `21-pr-complexity.md` |
| 22 | Refactoring Priorities | [analyze-refactoring-priorities](references/analyze-refactoring-priorities.md) | `22-refactoring-priorities.md` |
| 23 | Temporal Trends | [analyze-temporal-trends](references/analyze-temporal-trends.md) | `23-temporal-trends.md` |

### Forensic code analysis, Crime Scene (sections 24 to 33)

| # | Section | Reference | Output file |
|---|---------|-----------|-------------|
| 24 | Complexity Trends | [analyze-complexity-trends](references/analyze-complexity-trends.md) | `24-complexity-trends.md` |
| 25 | Code Age | [analyze-code-age](references/analyze-code-age.md) | `25-code-age.md` |
| 26 | Freshness Risk | [analyze-freshness-risk](references/analyze-freshness-risk.md) | `26-freshness-risk.md` |
| 27 | Parallel Development | [analyze-parallel-development](references/analyze-parallel-development.md) | `27-parallel-development.md` |
| 28 | Conway's Law Alignment | [analyze-conways-law](references/analyze-conways-law.md) | `28-conways-law.md` |
| 29 | Developer Patterns | [analyze-developer-patterns](references/analyze-developer-patterns.md) | `29-developer-patterns.md` |
| 30 | Defect Prediction | [analyze-defect-prediction](references/analyze-defect-prediction.md) | `30-defect-prediction.md` |
| 31 | Surprise Changes | [analyze-surprise-changes](references/analyze-surprise-changes.md) | `31-surprise-changes.md` |
| 32 | Off-Pattern Commits | [analyze-off-pattern-commits](references/analyze-off-pattern-commits.md) | `32-off-pattern-commits.md` |
| 33 | Code City | [analyze-code-city](references/analyze-code-city.md) | `33-code-city.md` |

## Output file format

Strict. Every section file is a standalone document:

```markdown
# {Section title from the table}

{output of the analysis}
```

Use the section title from the table, not the reference file's own title.

## Index file format

Strict. `$OUT_DIR/00-index.md`. Use `{REPO_NAME}/{SUBDIR}` as the name in the title for a subdirectory run, and add the line `Scope: {SUBDIR}` under the date.

```markdown
# Architecture Documentation: {REPO_NAME}

> Generated on: {CURRENT_DATE}
>
> This document provides comprehensive architecture documentation for the {REPO_NAME} repository.

## Sections

### Architecture & Structure

| # | Section | File | Status |
|---|---------|------|--------|
| 1 | [Project Overview](01-project-overview.md) | `01-project-overview.md` | |
...one row for each of sections 2 to 16...

### Behavioral Code Analysis (X-Rays)

...rows for sections 17 to 23, same columns...

### Forensic Code Analysis (Crime Scene)

...rows for sections 24 to 33, same columns...

## Document Information

| Attribute | Value |
|-----------|-------|
| Repository | {REPO_NAME} |
| Generated | {CURRENT_DATE} |
| Sections | 33 |
| Generator | architecture-tools full-analysis skill |
```

Take titles and file names from the section table. Put `skipped` or `failed` in the `Status` column for any section that did not finish, and leave it blank otherwise.

## Completion report

After the index is written, tell the user:

1. The path of `$OUT_DIR`.
2. Which sections found content and which reported nothing detected (a short list of numbers is enough).
3. Sections that were `skipped` or `failed`, with the reason for each.
4. A reminder that `.analysis/` is not git-ignored unless the repository already ignores it.

## Reference files

- The 33 files in `references/` are the per-section analysis prompts, one per row in the section table. They are bundled with the skill, so it has no plugin dependencies. Open one only when its section runs.
- [evals/test-prompts.md](evals/test-prompts.md) — three test prompts and the baseline behavior without the skill.
