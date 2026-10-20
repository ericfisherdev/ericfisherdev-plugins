# Test prompts for scriptify

Run each prompt in a fresh session with the skill on and again with it off. Compare against the expected outcome.

## Prompt 1: default window

> /scriptify

Expected with skill: the analyzer runs for the last two weeks, the report leads with the single best script, lists shapes best saving first with measured and estimated tokens, flags shapes already covered by opticlaude scripts, lists deny rules with conflicts checked against installed skills, and ends with "Reply with the script numbers to build." No files written.

Baseline without skill: a general suggestion to "automate repetitive tasks" without reading transcripts, or a scan of only the current session.

## Prompt 2: custom period and project

> /scriptify --period 3d --project obsidiboard

Expected with skill: the analyzer is called with `--period 3d --project obsidiboard`; the report says the window is 3 days and names only that project.

Baseline without skill: the flags are ignored or misread as a date range.

## Prompt 3: deny-rule conflict

> Find what I should script and tell me which commands I can block once the scripts exist.

Expected with skill: every proposed deny rule is checked against installed skills; a rule that a skill uses (for example `gh pr view`) is reported as skipped with the skill names rather than recommended.

Baseline without skill: deny rules proposed from the command names alone, breaking skills that call them.
