// minions: the main conversation is a dispatcher on a small model that never
// does the work itself. Every task goes to a minion on the model tier that
// fits it (see roster.ts), and the guards (guard.ts) refuse the dispatcher the
// tools that do work and refuse any spawn that names no model.

import type { Register, PromptComposeSection } from 'claude-code'
import { MINIONS, PLUGIN, ROUTING_TABLE, minionType } from './roster'
import { spawnDenial, toolCallDenial } from './guard'
import { resolveModelId } from './models'

const str = (v: unknown): string | undefined => (typeof v === 'string' && v !== '' ? v : undefined)

/** The section the dispatcher reads at the end of its system prompt. */
export const dispatcherSection = (model: string, isGuarded: boolean): PromptComposeSection => ({
  id: `${PLUGIN}:dispatcher`,
  scope: 'session',
  text: `# minions

This applies to the main conversation only. Inside a subagent, ignore this section and do the task you were given.

You are the dispatcher, running on ${model}. You NEVER do the work yourself: you do not read, search, edit, run commands or fetch pages. ${isGuarded ? 'Those tools are refused to you here.' : 'Treat those tools as off limits.'} For every task the user gives you, spawn a minion with the Agent tool (the \`subagent_type\` names the minion, its model is fixed), give it the whole task in its prompt, wait for its report, and relay what matters. Spawn independent minions in one message so they run in parallel.

Routing table:
${ROUTING_TABLE}

Any other agent type you spawn must name its \`model\` explicitly; a spawn that names none is refused.`,
})

/** The text `/minions` prints. */
export const statusText = (model: string, isGuarded: boolean): string =>
  [
    `minions: dispatcher on ${model}; guard ${isGuarded ? 'on' : 'off'} (/config › minions).`,
    '',
    'Routing table:',
    ROUTING_TABLE,
    '',
    'Minions:',
    ...MINIONS.map(m => `- ${minionType(m)}: ${m.model} at ${m.effort} effort`),
  ].join('\n')

export const register: Register = (on, options) => {
  const orchestratorModel = str(options['orchestratorModel']) ?? 'haiku'
  const orchestratorModelId = resolveModelId(orchestratorModel)
  const isGuarded = options['guard'] !== false

  on('session.start', async ($, e, next) => {
    for (const minion of MINIONS) {
      await $.agent.register({
        name: minion.name,
        description: minion.description,
        prompt: minion.prompt,
        model: minion.model,
        effort: minion.effort,
        ...(minion.tools === undefined ? {} : { tools: minion.tools }),
        ...(minion.disallowedTools === undefined ? {} : { disallowedTools: minion.disallowedTools }),
        ...(minion.omitClaudeMd === undefined ? {} : { omitClaudeMd: minion.omitClaudeMd }),
      })
    }
    await $.command.register({
      name: PLUGIN,
      description: 'The minions routing table, the dispatcher model and the guard state.',
    })
    $.ui.status(`minions: ${orchestratorModel}`)

    return next(e)
  })

  on('command.run', { command: PLUGIN }, () => ({ text: statusText(orchestratorModel, isGuarded) }))

  // The main conversation's every request goes to the dispatcher model; a
  // minion's requests keep its own.
  on('turn.step', async function* ($, e, next) {
    if (e.agentId !== undefined) return yield* next(e)

    return yield* next({ ...e, model: orchestratorModelId })
  })

  on('prompt.compose', async ($, e, next) => {
    const { sections } = await next(e)

    return { sections: [...sections, dispatcherSection(orchestratorModel, isGuarded)] }
  })

  if (isGuarded) {
    on('tool.call', ($, e, next) => {
      const deny = toolCallDenial({ tool: e.tool, agentId: e.agentId, origin: next.origin })

      return deny === undefined ? next(e) : { deny }
    }).catch(($, e, next) => (next.called ? next(e) : { deny: `${PLUGIN}: its guard failed.` }))
  }

  on('agent.spawn', ($, e, next) => {
    const deny = spawnDenial({
      subagentType: e.subagentType,
      model: e.model,
      parentAgentId: e.parentAgentId,
      fork: e.fork,
      isResume: e.resume !== undefined,
      isWorkflow: e.workflow !== undefined,
    })

    return deny === undefined ? next(e) : { deny }
  }).catch(($, e, next) => (next.called ? next(e) : { deny: `${PLUGIN}: its spawn guard failed.` }))
}
