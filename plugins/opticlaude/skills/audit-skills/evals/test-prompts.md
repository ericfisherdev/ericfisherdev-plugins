# Test prompts for audit-skills

Run each prompt in a fresh session with the skill on and again with it off. Compare against the expected outcome.

## Prompt 1: whole folder

> Audit every skill in ~/.claude/skills and tell me what to fix first.

Expected with skill: summary table, then every skill rule by rule with `file:line` evidence, then one numbered fix list, then a stop with "Reply with the fix numbers to apply." No files modified.

Baseline without skill: reads a few SKILL.md files, offers generic style feedback, no line numbers, no rule coverage, often starts editing.

## Prompt 2: one skill, mixed approval

> Check plugins/github-tools/skills/review-watch against the skill rules, then apply fixes 1 and 3 only.

Expected with skill: the report for one skill, then after the user's reply only fixes 1 and 3 applied, the skill re-audited, and a file-by-file summary. Fix 2 untouched.

Baseline without skill: applies whatever it thinks is wrong, including unrequested changes.

## Prompt 3: judgment rules

> Does my create-issue skill match the detail level to the risk, and does it ask Claude for its reasoning anywhere?

Expected with skill: a rule 3 verdict per step (costly steps locked, simple steps open) and a rule 13 verdict with line numbers or an explicit pass. Rule 3 reported as judgment, rule 13 backed by the script.

Baseline without skill: a general opinion with no per-step evidence.
