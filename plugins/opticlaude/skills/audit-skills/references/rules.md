# The 13 Skill-Writing Rules

Source: Anthropic's skill best-practices guide and the Claude Code skills docs, as collected in "The 10 SKILL Rules" (RoboNuggets). Each rule gives the source wording, how to check a skill for it, and the fix to recommend.

## Contents

- Rule 1: Progressive disclosure
- Rule 2: Contents lists
- Rule 3: Degrees of freedom
- Rule 4: Test on the models you use
- Rule 5: Optimise skill writing (and third-person descriptions)
- Rule 6: Workflows and checklists
- Rule 7: Feedback loops
- Rule 8: Common patterns (templates, examples, conditional workflows)
- Rule 9: Build for shareability
- Rule 10: Hooks for must-hold rules
- Rule 11: Build the test before the skill
- Rule 12: Most important instructions at the top
- Rule 13: Never request reasoning in the reply
- Fix-list ordering

## Rule 1: Progressive disclosure

Source: "Keep SKILL.md body under 500 lines for optimal performance." "SKILL.md serves as an overview that points Claude to detailed materials as needed." "Keep references one level deep from SKILL.md. All reference files should link directly from SKILL.md to ensure Claude reads complete files when needed." Claude may preview nested files with `head -100`, so anything reachable only through another file may be read incomplete.

Check:
- Count lines in SKILL.md after the frontmatter.
- List every file SKILL.md links to.
- Flag any file only linked from another file, never from SKILL.md.

Fix:
- Near 500 lines: move detail that only some jobs need into its own file, with a one-line pointer in SKILL.md saying when to read it.
- Nested file: link it straight from SKILL.md, or fold it into the file that uses it.

Script coverage: yes (body line count, direct links, nested links, orphans).

## Rule 2: Contents lists

Source: "For reference files longer than 100 lines, include a table of contents at the top. This ensures Claude can see the full scope of available information even when previewing with partial reads."

Check:
- Count lines in every file in the skill folder.
- For each file over 100 lines, look for a contents list in its first few lines.

Fix: add a `## Contents` heading at the top with one line per section, in the same order as the file.

Script coverage: yes (markdown and text files; SKILL.md over 100 lines is a warn, reference files are a fail).

## Rule 3: Degrees of freedom

Source: "Match the level of specificity to the task's fragility and variability." Low freedom: "Operations are fragile and error-prone" — specific scripts, few or no parameters. Medium: pseudocode or scripts with parameters, "a preferred pattern exists". High: text instructions, "multiple approaches are valid".

Check:
- For each step, ask what a mistake there would cost.
- Flag costly steps written loosely, and simple steps locked down hard.

Fix: lock costly steps to an exact script or command; loosen the rest to a plain goal. One skill can mix all three levels.

Script coverage: no — judgment. Read every step.

## Rule 4: Test on the models you use

Source: "Skills act as additions to models, so effectiveness depends on the underlying model. Test your Skill with all the models you plan to use it with." Haiku: "Does the Skill provide enough guidance?" Sonnet: "Is the Skill clear and efficient?" Opus/Fable: "Does the Skill avoid over-explaining?" "Skills developed for prior models are often too prescriptive for Claude Fable 5 and can degrade output quality. Review and consider removing older instructions if default performance is better."

Check:
- Note which model runs each skill.
- Flag older step-by-step instructions that look written for a weaker model as candidates to test.

Fix: test with the prescriptive text removed; keep the cut only if output is as good or better. Never delete on the audit alone.

Script coverage: no — judgment. Report as "candidate to test", not fail.

## Rule 5: Optimise skill writing

Source: "The context window is a public good." "Only add context Claude doesn't already have." Ask: "Does Claude really need this explanation?" and "Does this paragraph justify its token cost?" "Always write in third person. The description is injected into the system prompt, and inconsistent point-of-view can cause discovery problems." The description "should include both what the Skill does and when to use it."

Check:
- Flag any paragraph that explains general knowledge (what an invoice is, how git works).
- Read the description: does it say "I can" or "you can"? Does it say when to use the skill?

Fix:
- Cut to the author's own facts: prices, terms, clients, internal rules, project conventions.
- Write "Creates client invoices and sends payment reminders. Use when ...", not "I can help you with invoices".

Script coverage: partial (description voice, presence, length, trigger wording). General-knowledge paragraphs need a read.

## Rule 6: Workflows and checklists

Source: "Break complex operations into clear, sequential steps. For particularly complex workflows, provide a checklist that Claude can copy into its response and check off as it progresses." "Clear steps prevent Claude from skipping critical validation." Anthropic's example ends: "If verification fails, return to Step 2."

Check:
- Find every job with more than three or four steps.
- Look for numbered steps, a copyable checklist, and what happens when a check fails.

Fix: number the steps, add "Copy this checklist and track your progress:" with `- [ ] Step N` lines, and put a go-back line under each check step.

Script coverage: yes (numbered run over 4 steps, `- [ ]` checklist present, go-back phrase present).

## Rule 7: Feedback loops

Source: "Common pattern: Run validator → fix errors → repeat. This pattern greatly improves output quality." The validator can be a document: "The 'validator' is STYLE_GUIDE.md, and Claude performs the check by reading and comparing." "Make validation scripts verbose with specific error messages such as 'Field signature_date not found. Available fields: customer_name, order_total, signature_date_signed'."

Check:
- Find work where quality matters: client copy, documents, data.
- Is there a check, and does a fail send Claude back to fix it?
- Do scripts say what broke, or just "Error"?

Fix:
- Add a short checklist to review against, a revise step, and "only finish when every check passes".
- Make error messages name the problem and what does exist.

Script coverage: partial (generic error strings in scripts). The check-fix-repeat loop needs a read.

## Rule 8: Common patterns

Source:
- Template: "Provide templates for output format. Match the level of strictness to your needs." Strict: "ALWAYS use this exact template structure". Flexible: "Here is a sensible default format, but use your best judgment".
- Examples: where quality depends on seeing examples, "provide input/output pairs just like in regular prompting." "Examples convey the desired style and level of detail to Claude more clearly than descriptions alone."
- Conditional workflow: "Guide Claude through decision points." "Creating new content? → Follow 'Creation workflow' below." "Editing existing content? → Follow 'Editing workflow' below."

Check:
- Templates: does each say whether it is strict or a default?
- Style-heavy output: are there input/output pairs?
- Jobs that branch: is the fork written out?

Fix: add the strict-or-default line, two or three real example pairs, and an "if this, follow these steps" fork.

Script coverage: no — judgment.

## Rule 9: Build for shareability

Source: "Don't assume packages are available." Bad: "Use the pdf library to process the file." Good: "Install required package: `pip install pypdf`." "List required packages in your SKILL.md." On claude.ai, skills "can install packages from npm and PyPI"; on the Claude API a skill "has no network access and no runtime package installation". Use forward slashes in paths (`reference/guide.md`), never backslashes.

Check:
- List every package, command-line tool and script the skill uses.
- Look for paths that only exist on one machine, and backslashes.

Fix:
- Add a short "Needs" list to SKILL.md with each install line.
- Swap personal paths for paths inside the skill folder, `~`, or environment variables.

Script coverage: yes (personal paths, backslashes, third-party Python imports without an install line, known CLI tools without a Needs section).

## Rule 10: Hooks for must-hold rules

Source: "Claude skipped a rule that must hold every time: move the rule into a hook. Claude Code runs a hook every time its event occurs, such as before each file edit, whether or not Claude is following the skill. To keep the rule with the skill, define the hook in the skill's hooks frontmatter. That hook applies from the time the skill is invoked until the session ends." The `hooks` frontmatter field: "Hooks that Claude Code registers when the skill is invoked and keeps running for the rest of the session."

Check:
- Search the skill for never, always, must, and words in capitals.
- For each one, ask: would one miss cost money, data or a client?

Fix:
- Pick the few rules where one mistake really costs, and make those hooks. Say which event runs it (`PreToolUse` before a command or edit, `PostToolUse` after, `Stop` when the turn ends, `UserPromptSubmit` on each prompt) and show the script.
- Keep the rest as plain words, with the reason beside them.

Hooks docs: https://code.claude.com/docs/en/hooks#hooks-in-skills-and-agents

Script coverage: partial (lists the phrases and whether `hooks:` frontmatter exists). Which phrases are costly needs a read.

## Rule 11: Build the test before the skill

Source: "Create evaluations BEFORE writing extensive documentation. This ensures your Skill solves real problems rather than documenting imagined ones." Run Claude without a skill, "build three scenarios that test these gaps", measure the baseline, then "create just enough content to address the gaps and pass evaluations". "Run each one in a fresh session with the skill available and again with it turned off, and compare the results."

Check: does the skill folder hold at least three test prompts, and a note of the baseline run without the skill?

Fix: keep three real test tasks next to each skill (an `evals/` folder, an evals file, or a "Test prompts" section). Run them in a fresh chat with the skill on and off after every big change.

Script coverage: yes (evals folder, evals file, or a Test prompts / Evals heading).

## Rule 12: Most important instructions at the top

Source: "After compaction, Claude Code can keep only the start of an invoked skill, so put the most important instructions near the top of SKILL.md." When a long chat is summarised, Claude Code "re-attaches the most recent invocation of each skill after the summary, keeping the first 5,000 tokens of each."

Check: where in SKILL.md do the rules that must never be missed appear?

Fix: open SKILL.md with the few rules that must never be missed. Background, history and long examples go lower down or into their own files.

Script coverage: yes (position of the first must-hold phrase; warn when past 40% of the body in files over 40 lines).

## Rule 13: Never request reasoning in the reply

Source: "Prompts, skills, or harness instructions that tell the model to echo, transcribe, or explain its internal reasoning as response text may trigger the reasoning_extraction refusal category on Claude Fable 5." "Audit existing skills and system prompts for reflection or show-your-thinking instructions when migrating." "You can still ask for a short explanation of the answer or a summary of the actions taken." Opus 5.5 and Sonnet 5.5 guides agree: such requests "may be declined".

Check: lines that ask the model to narrate its step-by-step working, echo its thinking, or emit thinking tags as response text. The script's `REASONING_EXTRACTION_PATTERN` lists the exact phrases it matches.

Fix: ask for the answer plus a short explanation if one is needed.

Script coverage: yes (phrase match across SKILL.md and reference files).

## Fix-list ordering

Biggest impact first, so the user can approve the top of the list and stop:

1. Rule 13 fails and rule 9 personal-path fails — the skill can be declined or cannot run elsewhere.
2. Rule 1 (over 500 lines, nested files) and rule 12 — content is silently lost after compaction or a partial read.
3. Rules 2, 6, 7, 11 — partial reads, skipped checks, vague errors, no evals.
4. Rules 5, 8, 3 — token cost, discovery, missing templates or forks, wrong freedom level.
5. Rules 4 and 10 — candidates to test and hook candidates; both need a user decision beyond the audit.
