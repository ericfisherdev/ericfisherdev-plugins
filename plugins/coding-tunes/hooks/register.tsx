import type { EngineInterface, Register } from 'claude-code'

import type { TunesSnapshot } from '../types'
import { WORK_THRESHOLD_MS } from './coordination'
import type { HostPorts } from './ports'
import { buildServices } from './services'
import type { TunesServices } from './services'
import type { ControlOutcome } from './tunes-controls'
import { WinampView } from './winamp-view'

const SNAPSHOT = { plugin: 'coding-tunes', key: 'snapshot' } as const
const COMMAND = 'coding-tunes'
const PANE = 'coding-tunes'
const PANE_COLUMNS = 46
const PANE_ROWS = 9
const TICK_MS = 3000
/** The fullscreen layout docks a pane beside the transcript from this width. */
const DOCK_MIN_COLUMNS = 110

/** Why the pane sits above the prompt instead of docked top-right, if it does. */
const placementHint = (presentation: { isFullscreen: boolean; columns: number }): string | undefined => {
  if (!presentation.isFullscreen) {
    return 'The player sits above the prompt because this terminal uses the main-screen layout. It docks at the top right in the fullscreen layout, which CLAUDE_CODE_NO_FLICKER=0 and tmux turn off by default.'
  }
  if (presentation.columns < DOCK_MIN_COLUMNS) {
    return `The player sits above the prompt because the terminal is ${presentation.columns} columns wide; it docks at the top right from ${DOCK_MIN_COLUMNS}.`
  }

  return undefined
}

/** The engine interface as the plain ports the services take. */
const hostPortsFrom = async ($: EngineInterface): Promise<HostPorts> => ({
  runner: {
    run: (argv, timeoutMs) => $.process.run(argv, timeoutMs === undefined ? undefined : { timeoutMs }),
  },
  http: {
    request: async (url, init) => {
      const reply = await $.http.fetch(url, init)

      return { status: reply.status, ok: reply.ok, text: reply.text }
    },
  },
  files: {
    read: path => $.fs.read(path).then(text => text, () => undefined),
    write: (path, text) => $.fs.write(path, text),
    list: dir => $.fs.list(dir).then(entries => entries.map(entry => entry.name), () => []),
    remove: async path => {
      await $.process.run(['rm', '-f', '--', path])
    },
  },
  localFiles: {
    read: path => $.fs.read(path).then(text => text, () => undefined),
    exists: path => $.fs.exists(path),
  },
  store: {
    get: key => $.store.get(key),
    set: (key, value) => $.store.set(key, value),
  },
  clock: { now: () => $.clock.now() },
  snapshots: {
    show: async snapshot => {
      await $.state.set(SNAPSHOT, snapshot)
    },
  },
  notifier: {
    notify: text => $.ui.toast(text),
    log: text => $.ui.log(text),
  },
  prompter: { ask: (question, options) => $.ui.ask(question, options) },
  pluginRoot: $.plugin.root,
  runtimeDir: (await $.env.get('XDG_RUNTIME_DIR')) ?? '/tmp',
  homeDir: (await $.env.get('HOME')) ?? '',
  sessionId: await $.session.id(),
})

const EMPTY_SNAPSHOT: TunesSnapshot = {
  player: null,
  playlistId: null,
  track: '',
  isPlaying: false,
  elapsedSeconds: null,
  heldBy: null,
  isHeldHere: false,
  notice: null,
  frame: 0,
}

const openPane = ($: EngineInterface) => $.ui.open({ id: PANE, title: 'Coding Tunes', columns: PANE_COLUMNS, rows: PANE_ROWS })

export const register: Register = on => {
  let services: TunesServices | undefined

  on('session.start', async ($, e, next) => {
    const started = await next(e)
    const built = buildServices(await hostPortsFrom($), e.cwd)
    services = built
    await $.command.register({
      name: COMMAND,
      description: 'Play a YouTube Music or Spotify playlist while Claude works',
      argumentHint: '[--player=ytmusic|spotify] [--list=<playlist id>] | --setup | --stop',
    })
    $.clock.every(TICK_MS, () => void built.sync.reconcile())
    await built.sync.reconcile()
    const intent = await built.board.readIntent()
    if (e.isInteractive && intent?.isEnabled === true) void openPane($)

    return started
  })

  on('session.end', async ($, e, next) => {
    await services?.sync.end().catch(() => undefined)

    return next(e)
  })

  on('turn.start', async ($, e, next) => {
    if (services !== undefined) {
      const { activity, controls, sync } = services
      activity.beginTurn(await $.clock.now())
      await controls.clearOverride('paused')
      $.clock.after(WORK_THRESHOLD_MS + 250, () => void sync.reconcile())
      void sync.reconcile()
    }

    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (services !== undefined && e.agentId === undefined) {
      services.activity.endTurn()
      await services.controls.clearOverride('playing')
      await services.sync.reconcile()
    }

    return next(e)
  })

  // A question to the person holds the player paused until it is answered.
  on('tool.call', { tool: 'AskUserQuestion' }, async ($, e, next) => {
    const active = services
    if (active === undefined) return next(e)
    active.activity.openQuestion(e.tool_use_id)
    await active.sync.reconcile()
    try {
      return await next(e)
    } finally {
      active.activity.closeQuestion(e.tool_use_id)
      void active.sync.reconcile()
    }
  }).catch(($, e, next) => next(e))

  // Remember which calls the engine put to the person's decider.
  on('tool.check', async ($, e, next) => {
    const verdict = await next(e)
    if (verdict.decision === 'ask' && e.tool_use_id !== undefined) services?.activity.markAsked(e.tool_use_id)

    return verdict
  }).catch(($, e, next) => next(e))

  // The permission dialog is about to show: pause before it does.
  on('classic.PermissionRequest', async ($, e, next) => {
    if (services !== undefined) {
      services.activity.openPermissionPrompt()
      await services.sync.reconcile()
    }

    return next(e)
  }).catch(($, e, next) => next(e))

  // A call that went through the dialog has been answered once it settles.
  on('tool.call', async ($, e, next) => {
    const result = await next(e)
    if (services !== undefined) {
      const before = services.activity.holdReason()
      services.activity.settleToolCall(e.tool_use_id)
      if (services.activity.holdReason() !== before) void services.sync.reconcile()
    }

    return result
  }).catch(($, e, next) => next(e))

  on('command.run', { command: COMMAND }, async ($, e) => {
    if (services === undefined) return { text: 'Coding Tunes is still starting; try again in a moment.' }
    const text = await services.flow.run(e.args)
    const intent = await services.board.readIntent()
    if (intent?.isEnabled !== true) {
      await $.ui.close({ id: PANE })
      return { text }
    }
    await openPane($)
    const hint = placementHint(e.presentation)

    return { text: hint === undefined ? text : `${text}\n${hint}` }
  }).catch(() => ({ text: 'Coding Tunes hit an error; see claude --debug.' }))

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { value } = await $.state.get(SNAPSHOT)
    const active = services
    const act = (control: (current: TunesServices) => Promise<ControlOutcome>) => () => {
      if (active === undefined) return
      void control(active).then(
        outcome => {
          if (!outcome.isDone) $.ui.toast(outcome.reason)
        },
        (error: unknown) => $.ui.toast(error instanceof Error ? error.message : String(error)),
      )
    }

    return WinampView($.ui.resolve(e), value ?? EMPTY_SNAPSHOT, e.props.bodyColumns, {
      previous: act(current => current.controls.previous()),
      play: act(current => current.controls.play()),
      pause: act(current => current.controls.pause()),
      next: act(current => current.controls.next()),
    })
  })
}
