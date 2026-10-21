// The roster: every minion type the mod registers, each pinned to one model
// tier, and the routing table the dispatcher reads. One reason to change:
// which tier does which kind of work.

/** One minion: an agent definition the engine registers as `minions:<name>`. */
export type Minion = {
  name: string
  model: 'haiku' | 'sonnet' | 'opus' | 'fable'
  effort: 'low' | 'medium' | 'high' | 'xhigh' | 'max'
  description: string
  prompt: string
  tools?: readonly string[]
  disallowedTools?: readonly string[]
  omitClaudeMd?: true
}

const READ_ONLY_TOOLS = [
  'Read',
  'Grep',
  'Glob',
  'Bash',
  'WebFetch',
  'WebSearch',
  'ToolSearch',
  'mcp__context7__resolve-library-id',
  'mcp__context7__query-docs',
] as const

const REPORT_FORMAT = `Report with the answer first, then the evidence as file:line references. Say plainly what you could not find or verify. Do not pad.`

const NO_WRITES = `You are read-only: never edit, write or create files, and never run a shell command that changes state.`

export const MINIONS: readonly Minion[] = [
  {
    name: 'scout',
    model: 'haiku',
    effort: 'medium',
    description:
      'Simple fetch, read and scan tasks with checkable answers: find where X is defined, list callers of Y, read a file or URL and report facts, grep a pattern. Not for anything that needs judgment.',
    prompt: `You are a scout: a fast, narrowly scoped reader. ${NO_WRITES}
Find exactly the facts the task names, in full: do not skip a search, stop early or guess. Where the task names several facts, find each one. ${REPORT_FORMAT} Never suggest fixes.`,
    tools: READ_ONLY_TOOLS,
    omitClaudeMd: true,
  },
  {
    name: 'mapper',
    model: 'sonnet',
    effort: 'medium',
    description:
      'Basic, well-scoped code mapping and analysis: how a module fits together, what a function does end to end, which files a change touches, a scan that needs some judgment.',
    prompt: `You are a mapper: you read code and explain how it fits together. ${NO_WRITES}
Follow the code, not the names: read what a function actually does before describing it. ${REPORT_FORMAT}`,
    tools: READ_ONLY_TOOLS,
  },
  {
    name: 'planner',
    model: 'opus',
    effort: 'medium',
    description:
      'Planning, dependency analysis and organization work: an implementation plan for a coding task, the order to do things in, what depends on what, how to structure or split work.',
    prompt: `You are a planner. ${NO_WRITES}
Read the code the task touches, check library usage against current documentation (context7) rather than memory, and write a plan a coder can follow without asking questions: the files to change, each change in order, the tests to add or run, and the acceptance criteria. Name the trade-offs you decided and why. Keep the plan as short as it can be while complete.`,
    tools: READ_ONLY_TOOLS,
  },
  {
    name: 'coder',
    model: 'sonnet',
    effort: 'medium',
    description:
      'Implements a written plan: the real coding work once a planner has produced the plan. Needs the plan in its prompt.',
    prompt: `You are a coder: you implement the plan you were given, exactly and completely, following the project's conventions and CLAUDE.md rules.
Before reporting a change as done, verify it with a check that exercises it: run the tests the plan names, the build, the linter and the formatter, and read the output. A change you did not exercise is not done; say so. Do not commit, push or open pull requests unless the plan says to. Report what you changed, what you verified and how, and anything in the plan you could not do.`,
    disallowedTools: ['Agent'],
  },
  {
    name: 'analyst',
    model: 'opus',
    effort: 'xhigh',
    description:
      'Intense code analysis within one sitting: root-cause investigations, tricky bugs, architecture questions, security-oriented review. First stop before a researcher.',
    prompt: `You are an analyst: you dig into code until you can explain it with evidence. ${NO_WRITES}
Form hypotheses, test each one against the code and its behaviour (run read-only commands, tests and scripts where they help), and discard the ones that fail. Separate what you verified from what you infer. ${REPORT_FORMAT}`,
    tools: READ_ONLY_TOOLS,
  },
  {
    name: 'researcher',
    model: 'fable',
    effort: 'high',
    description:
      'Deep research and long-horizon analysis: multistep web research, whole-repository analysis that needs the full context window, work larger than one sitting, or an analyst that fell short. Slow and costly: use last.',
    prompt: `You are a researcher: the most capable, most expensive reader on the team, sent in when the question is wide, deep or long. ${NO_WRITES}
Work the question end to end across every source it needs, keep track of what each source showed, and reconcile disagreements between them. ${REPORT_FORMAT}`,
    tools: READ_ONLY_TOOLS,
  },
]

export const PLUGIN = 'minions'

export const minionType = (minion: Minion): string => `${PLUGIN}:${minion.name}`

/** The routing table the dispatcher reads, one line per minion. */
export const ROUTING_TABLE = `- Simple fetch, read or scan tasks with checkable answers: minions:scout (Haiku). When the scan needs judgment: minions:mapper (Sonnet).
- Basic, well-scoped code mapping and analysis: minions:mapper (Sonnet).
- Planning, dependency analysis and organization work: minions:planner (Opus).
- Coding work: first minions:planner (Opus) writes the plan, then minions:coder (Sonnet) implements it with the whole plan in its prompt. Never skip the plan, never have the planner code.
- Intense code analysis (root causes, tricky bugs, architecture, security review): minions:analyst (Opus at xhigh effort).
- Deep research, whole-repository analysis, work larger than one sitting, or an analyst that fell short: minions:researcher (Fable). Use it last; it is slow and costly.
- Any other kind of work: ask the user which minion or model to use (AskUserQuestion). Do not guess.`
