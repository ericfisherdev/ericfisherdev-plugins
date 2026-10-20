---
name: audit-skills
description: Audits installed Claude Code skills (personal, project, and plugin skills) against the 13 skill-writing rules from Anthropic's skill guide and reports every fail with file, line, and exact fix, then applies only the fixes the user approves by number. Use when the user asks to "audit skills", "audit my skills", "check my skills", "lint skills", "skill audit", "which skills break the rules", or wants a skill checked against best practices before sharing it.
---

# Audit Skills

Audit skills against the 13 skill-writing rules, report first, change nothing until the user approves fixes by number.

## Rules that hold every time

- **Never edit before approval.** No file in any skill folder is modified until the user replies with fix numbers. The audit is read-only.
- **Apply only approved numbers.** A fix the user did not list stays unapplied, even if it is trivial.
- **Every fail must carry evidence.** Each fail names the file and line number. A fail without a line is a judgment call and says so.
- **Always re-check after fixing.** Every changed skill is audited again. Remaining fails are fixed before the summary.

Why these are plain words, not hooks: a skill edit is recoverable (git, or the backup from Step 1), so one miss costs a revert, not money or data.

## Contents

- Needs
- Usage
- Workflow (Steps 1 to 7, with checklist)
- Reporting format
- Judgment rules the script cannot check
- Reference files

## Needs

- Python 3.8 or newer (standard library only, no packages).
- `scripts/audit_skills.py` — bundled in this skill folder.
- Read access to the skill folders being audited. Install locations:
  - Personal skills: `~/.claude/skills/<name>/SKILL.md`
  - Project skills: `.claude/skills/<name>/SKILL.md`
  - Plugin skills: the `installPath` entries in `~/.claude/plugins/installed_plugins.json`, under `skills/<name>/SKILL.md`

## Usage

```
/audit-skills                          # all installed skills (personal + project + plugins)
/audit-skills --personal               # only ~/.claude/skills
/audit-skills --project                # only ./.claude/skills
/audit-skills --plugins                # only skills inside installed plugins
/audit-skills <path> [<path> ...]      # specific skill folders or folders containing skills
/audit-skills --only name1,name2       # restrict to named skills (combine with a scope flag)
```

With no argument, audit everything. If the user has a big folder (over 15 skills) and did not name a scope, suggest starting with the five most-used skills or the ones that send money, delete things, or talk to clients, then proceed with whatever they pick.

## Workflow

Copy this checklist and track progress:

- [ ] Step 1: Confirm a backup exists
- [ ] Step 2: Run the mechanical checks
- [ ] Step 3: Read each SKILL.md for the judgment rules
- [ ] Step 4: Write the report and stop
- [ ] Step 5: Wait for approved fix numbers
- [ ] Step 6: Apply only those fixes
- [ ] Step 7: Re-audit changed skills and summarize

### Step 1: Confirm a backup exists

For each skill root being audited, check whether it is inside a git repository with a clean working tree (`git -C <root> status --porcelain`). If any root is not under git or has uncommitted changes, tell the user before Step 4 that fixes will be applied without an undo path and suggest `git init` or a plain folder copy. Do not create the backup yourself unless asked.

### Step 2: Run the mechanical checks

Run the bundled script with the scope the user asked for. The script path is relative to this skill folder:

```bash
python3 scripts/audit_skills.py --all
python3 scripts/audit_skills.py --personal --only review-watch,create-issue
python3 scripts/audit_skills.py ~/.claude/skills/my-skill
```

Exit codes: `0` no fails, `1` at least one fail, `2` nothing found or bad arguments. Add `--format json` when the output will be post-processed; add `--summary` for only the table.

The script decides rules 1, 2, 5, 6, 7, 9, 10, 11, 12 and 13. Treat its `fail` lines as fails, its `warn` lines as candidates to confirm by reading the file, and its `info` lines as context.

If the script errors (exit 2, or a `warning:` line naming a file it could not read), fix the path or scope and go back to Step 2.

### Step 3: Read each SKILL.md for the judgment rules

For every skill in scope, read SKILL.md in full and decide rules 3, 4 and 8. Confirm or dismiss each `warn` from Step 2 while reading. The exact check and fix for each rule is in [references/rules.md](references/rules.md); use its wording for the fix text.

- Rule 3 (degrees of freedom): for each step, ask what a mistake costs. Fail a costly step written loosely, and a trivial step locked to an exact script.
- Rule 4 (model fit): flag step-by-step instructions that look written for an older model as *candidates to test*, never as fails that delete text.
- Rule 8 (common patterns): templates must say strict or default; style-dependent output needs input/output pairs; branching jobs need a written fork.

Also check rule 10 by hand: for each must-hold phrase the script listed, decide whether one miss would cost money, data or a client. Only those are hook candidates; name the hook event (`PreToolUse`, `PostToolUse`, `Stop`, `UserPromptSubmit`) in the fix.

If a skill's SKILL.md is over 500 lines, read the first 150 lines plus every heading before judging rules 3, 4, 8; do not skip the skill.

### Step 4: Write the report and stop

Produce the report in the format below. End it with the numbered fix list and the line: "Reply with the fix numbers to apply." Then stop. Do not edit anything.

### Step 5: Wait for approved fix numbers

Accept any of: a list of numbers, a range, "all", or "none". Anything else: ask once for numbers. If the user says "all", confirm the count before applying when it exceeds 20.

### Step 6: Apply only those fixes

Apply the approved fixes, one skill at a time, using the fix text from the report. Rules for applying:

- Rule 1 splits: move the section into `references/<topic>.md`, keep a one-line pointer in SKILL.md saying when to read it, and add a contents list to the new file if it is over 100 lines.
- Rule 2 contents lists: a `## Contents` heading directly under the title, one line per section, in file order.
- Rule 5 descriptions: third person, what it does plus when to use it, keep every trigger phrase that was already there.
- Rule 9 install lines: a `## Needs` section naming each package with its install command (`pip install x`, `npm install x`) and each CLI tool.
- Rule 10 hooks: write the hook in the skill's `hooks:` frontmatter and show the script it runs; do not add a hook the user did not approve.
- Rule 13: replace lines that request the model's reasoning as output with "give the answer and a one-line explanation".

Never rewrite content outside the approved fix. Preserve the author's wording where the rule does not require a change.

### Step 7: Re-audit changed skills and summarize

Run `scripts/audit_skills.py` on every changed skill folder and re-read it for the judgment rules. If an approved fix still fails, or the fix introduced a new fail, go back to Step 6 for that skill. Finish with a short list of what changed, file by file, and anything still failing that the user did not approve.

## Reporting format

Keep this exact order, so the user can scan the table first and dig in second.

1. **Summary table** — one row per skill: skill name, path, number of fails, worst problem.
2. **Skill by skill, rule by rule** — for each skill, rules 1 to 13 in order, each marked `pass`, `fail`, or `n/a`. Every fail carries `file:line` evidence and the exact fix. Group all 13 rules under one heading per skill.
3. **Numbered fix list** — every fix across all skills in one list, biggest impact first. Ordering: rule 13 and rule 9 personal-path fails (break the skill or the request) first, then rule 1 and 12 (content lost after compaction or partial read), then rules 2, 6, 7, 11, then 5, 8, 3, then rule 4 and 10 candidates last.

Example of one rule line:

```
Rule 1  fail  SKILL.md:1 body is 555 lines (limit 500) — move "Ticket templates" (lines 310–480) to references/ticket-templates.md and link it from SKILL.md
Rule 3  pass
Rule 7  n/a   no quality-critical output in this skill
```

Example of one fix-list entry:

```
4. [jira-board-workflow] Rule 1 — move lines 310–480 ("Ticket templates") into references/ticket-templates.md, link from SKILL.md, add a Contents list to the new file.
```

Mark a rule `n/a` only with a reason (no scripts, no multi-step job, no templates). An `n/a` without a reason counts as unchecked.

## Judgment rules the script cannot check

The script never reports on rules 3, 4 and 8. A report that lists only script output is incomplete; Step 3 fills these in for every skill. When a rule needs a real run to decide (rule 4: "does Haiku get enough guidance?"), report it as "candidate to test" with the three prompts from the skill's own evals, not as a fail.

## Reference files

- [references/rules.md](references/rules.md) — the 13 rules: source quote, how to check, the fix. Read when writing fix text or deciding a borderline case.
- [evals/test-prompts.md](evals/test-prompts.md) — three test prompts for this skill and the baseline behaviour without it.
- `scripts/audit_skills.py` — the mechanical checker; `python3 scripts/audit_skills.py --help` lists every flag.
