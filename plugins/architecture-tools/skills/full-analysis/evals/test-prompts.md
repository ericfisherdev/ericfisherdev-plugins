# Test prompts for full-analysis

Run each prompt in a fresh session with the skill on and again with it off. Compare against the expected outcome.

## Prompt 1: whole repository

> Run a full analysis of this repo.

Expected with skill: `.analysis/full/` holds `00-index.md` plus `01-` to `33-` files, each titled with the section name from the table. Sections with nothing to find still have a file saying what was checked. A short completion report lists skipped or failed sections.

Baseline without skill: one long chat answer or a few ad-hoc files, no numbered set, no index, several areas (events, feature flags, ML) silently left out.

## Prompt 2: subdirectory scope

> /full-analysis apps/frontend

Expected with skill: output in `.analysis/full/apps.frontend/`, every command and search limited to `apps/frontend`, index title names the repo and subdirectory. A missing directory stops the run with a clear message and no files written.

Baseline without skill: analyzes the whole repo or asks which folder, no scoped output directory.

## Prompt 3: missing `gh` login

> Do the full analysis. I have not logged in to gh.

Expected with skill: section 21 is skipped with a one-line reason in `21-pr-complexity.md`, the index marks it `skipped`, and sections 1 to 20 and 22 to 33 still complete.

Baseline without skill: the run stops at the first `gh` error or drops the PR section without a record.
