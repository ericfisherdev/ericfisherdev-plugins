---
name: scriptify
description: Scans Claude Code session transcripts for repetitive tool calls, ranks them by the tokens a purpose-built script would save, and proposes the scripts plus the deny rules that would enforce them. Use when the user runs "/scriptify", asks "what should I script", "which commands waste the most tokens", "find repetitive tasks in my sessions", or wants to turn recurring shell work into scripts.
---

# Scriptify

Measure first, propose second, write nothing until the user picks.

## Rules that hold every time

- **Report before building.** The deliverable is the ranked report. Scripts are written only after the user names which ones.
- **Every number is measured or labelled an estimate.** Measured tokens come from the transcripts; estimated savings are measured tokens times the factor the script prints. Say which is which.
- **Deny rules need a conflict check.** Before proposing a `Bash(...)` deny rule, grep installed skills for the command; a rule that breaks a skill is listed as skipped with the skill names.

## Contents

- Needs
- Usage
- Workflow (Steps 1 to 4)
- Reporting format

## Needs

- Python 3.10 or newer, standard library only.
- `scripts/scriptify.py`, bundled in this skill folder.
- Read access to `~/.claude/projects` (or `$CLAUDE_CONFIG_DIR/projects`).

## Usage

```
/scriptify                      # last 2 weeks, every project
/scriptify --period 1w          # last week (units: h, d, w)
/scriptify --period 2d --project obsidiboard
```

Pass every flag the user gives straight to the script. `--period` defaults to `2w`.

## Workflow

Copy this checklist and track progress:

- [ ] Step 1: Run the analyzer
- [ ] Step 2: Read the ranked shapes
- [ ] Step 3: Check deny-rule conflicts
- [ ] Step 4: Write the report and stop

### Step 1: Run the analyzer

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/scriptify/scripts/scriptify.py --period 2w
```

Add `--format json` when the report will be post-processed, `--top N` to see more shapes, `--project NAME` to restrict to one project. Exit code 1 means the window held no tool calls, exit code 2 a missing transcript directory. If the check fails, fix the flag or path and go back to Step 1.

### Step 2: Read the ranked shapes

For each shape in the table, decide whether a script can replace it:

- A shape marked `covered by` already has a script in this plugin. Do not propose a new one; tell the user to run `/opticlaude:setup` (or re-run it) and skip the shape.
- A shape whose examples differ only in arguments (paths, repo names, IDs) is a script with flags.
- A shape whose examples differ in logic (one-off analysis snippets) is not; say so and move on.
- Use the "Verbatim repeated commands" section for exact repeats that belong in a script or an alias.

### Step 3: Check deny-rule conflicts

For every command a proposed script would replace entirely, search the installed skills before suggesting a deny rule:

```bash
grep -rlE '<command regex>' ~/.claude/skills ~/.claude/plugins/marketplaces ~/.claude/plugins/cache 2>/dev/null
```

A hit means the rule is reported as *skipped* with the skill names, because deny beats allow and the skill would fail. If a proposed rule has no grep result but the command also appears in a `covered by` shape, go back to Step 2 and mark the shape as already covered instead.

### Step 4: Write the report and stop

Produce the report below, end with "Reply with the script numbers to build.", and stop. When the user replies, write the chosen scripts to `~/.claude/scripts/` (or the path they name), test each on real input, and add the non-conflicting deny rules to `permissions.deny` in `~/.claude/settings.json` plus one pointer line per script in the global CLAUDE.md.

## Reporting format

1. **Headline**: the single script with the largest estimated saving, in one sentence with its measured cost and estimate.
2. **Ranked list**, best saving first. Each entry: proposed script name and interface, the shape it replaces, calls and sessions, measured tokens, estimated saving, and the deny rules it allows (or "no safe deny rule" with the reason).
3. **Already covered**: shapes handled by existing opticlaude scripts, with the reminder to run `/opticlaude:setup`.
4. **Not scriptable**: shapes the analyzer flagged that do not repeat in a scriptable way (same-file re-reads, ad hoc ssh), with the one-line mitigation.
5. The closing line: "Reply with the script numbers to build."

## Reference files

- [evals/test-prompts.md](evals/test-prompts.md): three test prompts and the baseline behaviour without this skill; read when changing the workflow.
- `scripts/scriptify.py`: the analyzer; `--help` lists every flag and the savings factors.
