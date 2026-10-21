import { test, expect } from 'claude-code/testing'
import { isWorkTool, spawnDenial, toolCallDenial } from '../hooks/guard'
import { MINIONS, minionType } from '../hooks/roster'
import { MODEL_IDS, resolveModelId } from '../hooks/models'
import { dispatcherSection, statusText } from '../hooks/register'

// ---------- the roster ----------

test('every minion is pinned to a model tier and named under the plugin', () => {
  const names = MINIONS.map(minionType)
  expect(names).toEqual([
    'minions:scout',
    'minions:mapper',
    'minions:planner',
    'minions:coder',
    'minions:analyst',
    'minions:researcher',
  ])
  expect(MINIONS.map(m => m.model)).toEqual(['haiku', 'sonnet', 'opus', 'sonnet', 'opus', 'fable'])
  for (const minion of MINIONS) expect(minion.prompt.length).toBeGreaterThan(50)
})

const FILE_WRITING_TOOLS = ['Edit', 'Write', 'MultiEdit', 'NotebookEdit']

test('only the coder holds file-writing tools; the others are read-only by instruction', () => {
  for (const minion of MINIONS) {
    if (minion.name === 'coder') {
      expect(minion.tools).toBeUndefined()
      expect(minion.disallowedTools).toEqual(['Agent'])
    } else {
      expect(minion.tools).toBeDefined()
      for (const tool of FILE_WRITING_TOOLS) expect(minion.tools).not.toContain(tool)
      expect(minion.prompt).toMatch(/You are read-only/)
    }
  }
})

test('the scout has no shell; the minions that read git history and run tests keep one', () => {
  const byName = Object.fromEntries(MINIONS.map(m => [m.name, m]))
  expect(byName['scout']?.tools).not.toContain('Bash')
  for (const name of ['mapper', 'planner', 'analyst', 'researcher']) expect(byName[name]?.tools).toContain('Bash')
})

test('the planner reaches context7 whether the user configured the server or the plugin ships it', () => {
  const planner = MINIONS.find(m => m.name === 'planner')
  expect(planner?.tools).toContain('mcp__context7__query-docs')
  expect(planner?.tools).toContain('mcp__plugin_context7_context7__query-docs')
})

// ---------- the model aliases ----------

test('an alias resolves to its full id and anything else passes through', () => {
  for (const [alias, id] of Object.entries(MODEL_IDS)) expect(resolveModelId(alias)).toBe(id)
  expect(resolveModelId('haiku')).toBe('claude-haiku-5-5')
  expect(resolveModelId('fable')).toBe('claude-fable-5-1')
  expect(resolveModelId('claude-opus-5-5')).toBe('claude-opus-5-5')
  expect(resolveModelId('constructor')).toBe('constructor')
  expect(resolveModelId('toString')).toBe('toString')
})

// ---------- the tool guard ----------

test('every tool but the orchestration tools is work, unknown tools included', () => {
  const work = [
    'Read', 'Edit', 'Write', 'MultiEdit', 'NotebookEdit',
    'Bash', 'PowerShell', 'Monitor', 'REPL', 'JavaScript', 'AppifactRepl', 'Workflow',
    'Grep', 'Glob', 'WebFetch', 'WebSearch', 'LSP', 'Artifact',
    'mcp__context7__query-docs', 'mcp__plugin_context7_context7__query-docs',
    'SomeToolALaterEngineAdds',
  ]
  for (const tool of work) expect(isWorkTool(tool)).toBe(true)
  for (const tool of ['Agent', 'AskUserQuestion', 'SendMessage', 'ListAgents', 'TaskStop', 'ToolSearch', 'Skill', 'TodoWrite', 'ExitPlanMode']) {
    expect(isWorkTool(tool)).toBe(false)
  }
})

const engine = { plugin: 'engine' }

test('the main conversation is refused work tools and keeps the rest', () => {
  expect(toolCallDenial({ tool: 'Bash', origin: engine })).toMatch(/never does the work itself/)
  expect(toolCallDenial({ tool: 'Read', origin: engine })).toMatch(/minions:scout/)
  expect(toolCallDenial({ tool: 'mcp__context7__query-docs', origin: engine })).toMatch(/minions:/)
  expect(toolCallDenial({ tool: 'Agent', origin: engine })).toBeUndefined()
  expect(toolCallDenial({ tool: 'AskUserQuestion', origin: engine })).toBeUndefined()
})

test('a minion and another plugin run work tools untouched', () => {
  expect(toolCallDenial({ tool: 'Bash', agentId: 'agent-1', origin: engine })).toBeUndefined()
  expect(toolCallDenial({ tool: 'Edit', origin: { plugin: 'noto-mode' } })).toBeUndefined()
})

// ---------- the spawn guard ----------

const spawn = (over: Partial<Parameters<typeof spawnDenial>[0]>) =>
  spawnDenial({ subagentType: 'general-purpose', fork: false, isResume: false, isWorkflow: false, ...over })

test('a spawn from the main conversation must be a minion or name a model', () => {
  expect(spawn({})).toMatch(/names no model/)
  expect(spawn({ subagentType: 'Explore' })).toMatch(/Explore names no model/)
  expect(spawn({ subagentType: 'minions:scout' })).toBeUndefined()
  expect(spawn({ model: 'opus' })).toBeUndefined()
})

test('forks, resumes, workflow agents and nested spawns are never refused', () => {
  expect(spawn({ fork: true })).toBeUndefined()
  expect(spawn({ isResume: true })).toBeUndefined()
  expect(spawn({ isWorkflow: true })).toBeUndefined()
  expect(spawn({ parentAgentId: 'agent-1' })).toBeUndefined()
})

// ---------- the dispatcher's text ----------

test('the dispatcher section names every minion and tells subagents to ignore it', () => {
  const section = dispatcherSection('haiku', true)
  expect(section.id).toBe('minions:dispatcher')
  expect(section.scope).toBe('session')
  expect(section.text).toMatch(/Inside a subagent, ignore this section/)
  for (const minion of MINIONS) expect(section.text).toContain(minionType(minion))
  expect(section.text).toMatch(/refused to you here/)
  expect(dispatcherSection('haiku', false).text).toMatch(/off limits/)
})

test('/minions prints the model, the guard state and the roster', () => {
  const text = statusText('haiku', false)
  expect(text).toMatch(/dispatcher on haiku; guard off/)
  expect(text).toMatch(/minions:researcher: fable at high effort/)
})

// ---------- against the engine ----------

test('session.start registers every minion and the command, then marks the status line', async ($, on) => {
  const registered: string[] = []
  let command: string | undefined
  let status: string | undefined
  on('agent.register', (_, e) => {
    registered.push(e.name)
    return { value: { agent: `minions:${e.name}` } }
  })
  on('command.register', (_, e) => {
    command = e.name
    return { value: { command: e.name } }
  })
  on('ui.status', (_, e) => {
    status = e.text
    return { value: undefined }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))

  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })

  expect(registered).toEqual(MINIONS.map(m => m.name))
  expect(command).toBe('minions')
  expect(status).toBe('minions: haiku')
})

test('the main conversation steps on the dispatcher model; a minion keeps its own', async ($, on) => {
  const sent: { model: string; agentId?: string }[] = []
  // Stands for the engine beneath: records the request it would send.
  on('turn.step', async function* (_, e) {
    sent.push({ model: e.model, agentId: e.agentId })
    return { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: 'end_turn' as const, usage: null }
  })

  const step = async (input: { model: string; agentId?: string }) => {
    const stream = $.turn.step({ turnId: 'turn-1', index: 0, messageCount: 1, ...input })
    for await (const _chunk of stream) { /* drain */ }
    return stream.result
  }

  await step({ model: 'claude-fable-5-1' })
  await step({ model: 'claude-sonnet-5-5', agentId: 'agent-1' })

  expect(sent).toEqual([
    { model: 'claude-haiku-5-5', agentId: undefined },
    { model: 'claude-sonnet-5-5', agentId: 'agent-1' },
  ])
})

test("the engine's own Bash call in the main conversation is refused and nothing runs beneath", async ($, on) => {
  let ran = 0
  on('tool.call', () => {
    ran += 1
    return { result: {} }
  })

  const denied = await $.tool.call({ tool: 'Bash', command: 'ls' })
  expect(denied.deny).toMatch(/never does the work itself/)
  expect(ran).toBe(0)
})

test("a shell tool the denylist never named is refused too", async ($, on) => {
  on('tool.call', () => ({ result: {} }))

  const denied = await $.tool.call({ tool: 'Monitor', command: 'ls' } as never)
  expect(denied.deny).toMatch(/never does the work itself/)
})
