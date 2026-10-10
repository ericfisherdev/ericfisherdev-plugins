// The decision for one tool call, in auto mode's documented order:
//   read-only actions and edits inside the working directories: allow;
//   the block list: ask (never approved on the mod's own say-so);
//   everything else: classify (a model judges, or the person is asked).
// Pure: no engine access, so `tests/` can drive it directly.

import { type Context, normalizePath, isInsideAny, NEVER_WRITE, SENSITIVE } from './paths'
import { judgeShell } from './shell-policy'
import { type Decision, allow, ask, classify, ADD_DIR_FIX } from './decision'

export type { Decision, Kind } from './decision'
export { allow, ask, classify, worse, NEVER_FIX, ADD_DIR_FIX, CLASSIFIER_FIX } from './decision'

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

const str = (v: unknown): string | undefined => (typeof v === 'string' && v !== '' ? v : undefined)

/** Tools whose dialog the person must answer; a hook cannot dismiss it anyway. */
const PERSON_TOOLS = new Set(['AskUserQuestion', 'ExitPlanMode', 'EnterPlanMode'])
/** Tools that change nothing outside the session. */
const READ_ONLY_TOOLS = new Set([
  'WebFetch', 'WebSearch', 'ToolSearch', 'TodoWrite', 'TodoRead', 'BashOutput', 'KillShell', 'KillBash', 'TaskOutput',
  'TaskStop', 'ListMcpResourcesTool', 'ReadMcpResourceTool', 'Skill', 'ListAgents', 'CronList', 'Monitor',
])
const READ_FILE_TOOLS = new Set(['Read', 'Glob', 'Grep', 'LS', 'NotebookRead'])
const WRITE_FILE_TOOLS = new Set(['Edit', 'Write', 'MultiEdit', 'NotebookEdit'])

const pathOf = (args: Record<string, unknown>): string | undefined =>
  str(args['file_path']) ?? str(args['notebook_path']) ?? str(args['path'])

/** The path as a permissions rule spells it: project-relative, or `//absolute`. */
export function ruleSpelling(path: string, ctx: Context): string {
  const cwd = normalizePath(ctx.cwd, ctx.cwd) ?? ctx.cwd
  if (path.startsWith(`${cwd}/`)) return path.slice(cwd.length + 1)
  return `//${path.replace(/^\//, '')}`
}

/** A permissions.allow rule that would approve this call, for the prompt's hint. */
export function suggestRule(tool: string, input: unknown, ctx: Context): string {
  const args = isRecord(input) ? input : {}
  if (tool === 'Bash' || tool === 'PowerShell') {
    const words = (str(args['command']) ?? '').trim().split(/\s+/).filter(Boolean)
    const head = words[0] ?? ''
    const second = words[1]
    const prefix = second !== undefined && !second.startsWith('-') && !/[|;&<>]/.test(head) ? `${head} ${second}` : head
    return `${tool}(${prefix}:*)`
  }
  if (READ_FILE_TOOLS.has(tool) || WRITE_FILE_TOOLS.has(tool)) {
    const spelling = pathOf(args)
    const p = spelling === undefined ? undefined : normalizePath(spelling, ctx.cwd)
    return p === undefined ? tool : `${tool}(${ruleSpelling(p, ctx)})`
  }
  if (tool === 'WebFetch') {
    const url = str(args['url'])
    const host = url === undefined ? undefined : /^[a-z]+:\/\/([^/:?#]+)/i.exec(url)?.[1]
    return host === undefined ? tool : `WebFetch(domain:${host})`
  }
  return tool
}

/** Decides one tool call. `input` is the tool's arguments as the permission check reads them. */
export function judge(tool: string, input: unknown, ctx: Context): Decision {
  const args = isRecord(input) ? input : {}
  if (PERSON_TOOLS.has(tool)) return ask('a dialog only you can answer', 'nothing to change: this dialog is yours by design')
  if (READ_ONLY_TOOLS.has(tool)) return allow(`${tool} changes nothing`)
  if (READ_FILE_TOOLS.has(tool)) return judgeFileRead(tool, args, ctx)
  if (WRITE_FILE_TOOLS.has(tool)) return judgeFileWrite(tool, args, ctx)
  if (tool === 'Bash' || tool === 'PowerShell') {
    return judgeShell(str(args['command']) ?? '', tool === 'PowerShell' ? 'powershell' : 'sh', ctx)
  }
  if (tool === 'Agent' || tool === 'Workflow') return classify(`${tool} starts other agents`)
  if (tool.startsWith('mcp__')) return classify('an MCP tool; nothing says what it changes')
  return classify(`${tool} is not in the rule set`)
}

function judgeFileRead(tool: string, args: Record<string, unknown>, ctx: Context): Decision {
  const spelling = pathOf(args)
  if (spelling === undefined) return allow(`${tool} over the working directory`)
  const p = normalizePath(spelling, ctx.cwd)
  if (p === undefined) return classify('a path spelling only the shell expands')
  if (SENSITIVE.test(p)) {
    return classify('reads a credentials, startup or instructions file', `add an allow rule like ${tool}(${ruleSpelling(p, ctx)}) if this file is fine to read`)
  }
  if (isInsideAny(p, ctx.workingDirs)) return allow('a read inside the working directories')
  return ask(
    'a read outside the working directories; auto mode prompts for the first of these too',
    `${ADD_DIR_FIX}, or add an allow rule like ${tool}(${ruleSpelling(p, ctx)})`,
  )
}

function judgeFileWrite(tool: string, args: Record<string, unknown>, ctx: Context): Decision {
  const spelling = pathOf(args)
  if (spelling === undefined) return classify('no path to check')
  const p = normalizePath(spelling, ctx.cwd)
  if (p === undefined) return classify('a path spelling only the shell expands')
  if (NEVER_WRITE.test(p)) return ask("writes Claude Code's own settings, hooks, plugins or git hooks")
  if (SENSITIVE.test(p)) {
    return classify('edits a credentials, startup or instructions file', `add an allow rule like ${tool}(${ruleSpelling(p, ctx)}) if this file is yours to edit freely`)
  }
  if (isInsideAny(p, ctx.workingDirs)) return allow('an edit inside the working directories')
  return classify('an edit outside the working directories', `${ADD_DIR_FIX}, or add an allow rule like ${tool}(${ruleSpelling(p, ctx)})`)
}
