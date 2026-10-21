// The guards: pure decisions about what the main conversation may do itself.
// No `$`, no engine: a function of the event's facts, so the tests read them
// without a session. One reason to change: what counts as doing the work.

import { PLUGIN } from './roster'

/**
 * The tools the dispatcher keeps: spawning and steering minions, asking the
 * user, tracking tasks, loading skills and tool schemas, and leaving plan
 * mode. An allowlist, so a tool this list does not name (every file, shell,
 * code-execution, search, web and MCP tool, and any tool a later engine adds)
 * is refused rather than slipping through.
 */
const ORCHESTRATION_TOOLS: ReadonlySet<string> = new Set([
  'Agent',
  'AskUserQuestion',
  'SendMessage',
  'ListAgents',
  'TaskStop',
  'FetchInboxMessage',
  'ToolSearch',
  'Skill',
  'TodoWrite',
  'TaskCreate',
  'TaskGet',
  'TaskList',
  'TaskUpdate',
  'GetTask',
  'EnterPlanMode',
  'ExitPlanMode',
  'SendFeedback',
])

/** True when `tool` does work the dispatcher must hand to a minion. */
export const isWorkTool = (tool: string): boolean => !ORCHESTRATION_TOOLS.has(tool)

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
