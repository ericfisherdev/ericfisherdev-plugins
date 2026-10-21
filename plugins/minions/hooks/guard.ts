// The guards: pure decisions about what the main conversation may do itself.
// No `$`, no engine: a function of the event's facts, so the tests read them
// without a session. One reason to change: what counts as doing the work.

import { PLUGIN } from './roster'

/** The tools that do work: file, shell, search and web access. */
const WORK_TOOLS: ReadonlySet<string> = new Set([
  'Read',
  'Edit',
  'Write',
  'MultiEdit',
  'NotebookEdit',
  'Bash',
  'Grep',
  'Glob',
  'WebFetch',
  'WebSearch',
  'LSP',
])

const isMcpTool = (tool: string): boolean => tool.startsWith('mcp__')

/** True when `tool` does work the dispatcher must hand to a minion. */
export const isWorkTool = (tool: string): boolean => WORK_TOOLS.has(tool) || isMcpTool(tool)

/** The facts of a tool call the guard reads. */
export type ToolCallFacts = {
  tool: string
  /** The loop the call runs in; absent on the main conversation. */
  agentId?: string
  /** Who raised the call: `engine` for the model's own call, a plugin's name for one its hook made. */
  origin: { readonly plugin: string }
}

const ENGINE = 'engine'

const isModelsOwnCall = (call: ToolCallFacts): boolean => call.origin.plugin === ENGINE

/**
 * Why a tool call in the main conversation is refused, or undefined to let it
 * run. A minion's call, and a call another plugin makes, always runs.
 */
export const toolCallDenial = (call: ToolCallFacts): string | undefined => {
  if (call.agentId !== undefined || !isModelsOwnCall(call)) return undefined
  if (!isWorkTool(call.tool)) return undefined

  return `${PLUGIN}: the main conversation never does the work itself. Spawn a minion with the Agent tool: minions:scout for reads and scans, minions:mapper for code mapping, minions:planner for plans, minions:coder for a written plan, minions:analyst for deep code analysis, minions:researcher for deep research. Ask the user when none fits.`
}

/** The facts of an agent spawn the guard reads. */
export type SpawnFacts = {
  subagentType: string
  model?: string
  /** The loop the spawn happens in; absent on the main conversation. */
  parentAgentId?: string
  fork: boolean
  isResume: boolean
  isWorkflow: boolean
}

const isMinion = (subagentType: string): boolean => subagentType.startsWith(`${PLUGIN}:`)

/**
 * Why a spawn from the main conversation is refused, or undefined to let it
 * start: a minion carries its model; any other type must name one, so no
 * agent runs on a tier nobody chose.
 */
export const spawnDenial = (spawn: SpawnFacts): string | undefined => {
  if (spawn.parentAgentId !== undefined) return undefined
  if (spawn.fork || spawn.isResume || spawn.isWorkflow) return undefined
  if (isMinion(spawn.subagentType) || spawn.model !== undefined) return undefined

  return `${PLUGIN}: ${spawn.subagentType} names no model. Use a minions:* type, or pass model (haiku, sonnet, opus or fable) per the routing table; ask the user when no row fits.`
}
