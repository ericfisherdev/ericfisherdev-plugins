import { describe, expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'

import { SHARED_ROOT, installFakeHost, writeForeignSession } from './fake-host'

const PLAYLIST = 'PLQtABrboQ1MRguCL9d1Z7_v3owvB80vHY'
const PANE_PROPS = {
  title: 'Coding Tunes',
  isFocused: false,
  bodyColumns: 46,
  placement: 'dock' as const,
  scroll: { offset: 0, bodyRows: 12 },
  view: {},
}

const startSession = async ($: Engine): Promise<void> => {
  await $.session.start({ cwd: '/home/me/proj', surface: 'terminal', isInteractive: true })
  await $.command.run({
    command: 'coding-tunes',
    args: `--player=ytmusic --list=${PLAYLIST}`,
    origin: { kind: 'composer' },
    presentation: { isFullscreen: true, columns: 160 },
  })
}

describe('automatic playback', () => {
  test('plays once Claude has worked 10 seconds and pauses when the turn ends', async ($, on) => {
    const host = installFakeHost(on, 'session-mine')
    await startSession($)
    expect(host.mpvCommands).toContain('ensure')

    await $.turn.start({ text: 'refactor it', turnId: 'turn-1' })
    await host.clock.advance(9_000)
    expect(host.isMpvPlaying()).toBe(false)

    await host.clock.advance(2_000)
    expect(host.isMpvPlaying()).toBe(true)

    await $.turn.complete({ reason: 'answer', answer: 'done', durationMs: 11_000, isAborted: false, turnId: 'turn-1' })
    expect(host.isMpvPlaying()).toBe(false)
  })

  test('a question to the person pauses playback until it is answered', async ($, on) => {
    const host = installFakeHost(on, 'session-mine')
    let wasPlayingDuringQuestion: boolean | undefined
    on('tool.check', () => ({ decision: 'allow' as const }))
    on('tool.call', { tool: 'AskUserQuestion' }, () => {
      wasPlayingDuringQuestion = host.isMpvPlaying()
      return { deny: 'answered by the test' }
    })
    await startSession($)
    await $.turn.start({ text: 'plan it', turnId: 'turn-1' })
    await host.clock.advance(11_000)
    expect(host.isMpvPlaying()).toBe(true)

    await $.tool.call({ tool: 'AskUserQuestion', questions: [] } as never)
    expect(wasPlayingDuringQuestion).toBe(false)

    await host.clock.advance(3_000)
    expect(host.isMpvPlaying()).toBe(true)
  })
})

describe('slash-command controls', () => {
  const command = ($: Engine, args: string) =>
    $.command.run({ command: 'coding-tunes', args, origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 120 } })

  test('--pause, --next and --play drive the player mid-turn, as the pane buttons do', async ($, on) => {
    const host = installFakeHost(on, 'session-mine')
    await startSession($)
    await $.turn.start({ text: 'long job', turnId: 'turn-1' })
    await host.clock.advance(11_000)
    expect(host.isMpvPlaying()).toBe(true)

    expect((await command($, '--pause')).text).toContain('Paused')
    expect(host.isMpvPlaying()).toBe(false)
    await command($, '--next')
    expect(host.mpvCommands).toContain('next')
    await command($, '--play')
    expect(host.isMpvPlaying()).toBe(true)
  })

  test('--play is refused while another session waits on input', async ($, on) => {
    const host = installFakeHost(on, 'session-mine')
    await startSession($)
    writeForeignSession(host, 'session-other', 'question')
    expect((await command($, '--play')).text).toContain('waiting for your input')
    expect(host.isMpvPlaying()).toBe(false)
  })

  test('a command that would ask a question is refused while Claude works', async ($, on) => {
    const host = installFakeHost(on, 'session-mine')
    await startSession($)
    await $.turn.start({ text: 'long job', turnId: 'turn-1' })
    expect((await command($, '--setup')).text).toContain('once Claude is idle')
    expect((await command($, '')).text).toContain('once Claude is idle')
    await host.clock.advance(0)
  })
})

describe('browser login', () => {
  test('a saved browser login is passed to mpv as the yt-dlp cookie source', async ($, on) => {
    const zen = { label: 'Zen', browser: 'firefox', profile: '/home/me/.zen/abc.Default (alpha)' }
    const host = installFakeHost(on, 'session-mine', { ytCookieSource: zen })
    await startSession($)
    expect(host.ensureArgs.at(-1)).toEqual([
      `https://music.youtube.com/playlist?list=${PLAYLIST}`,
      'firefox:/home/me/.zen/abc.Default (alpha)',
    ])
  })

  test('with no saved login, mpv gets an empty cookie source', async ($, on) => {
    const host = installFakeHost(on, 'session-mine')
    await startSession($)
    expect(host.ensureArgs.at(-1)?.[1]).toBe('')
  })
})

describe('playlist errors', () => {
  test('a playlist YouTube refuses is reported instead of failing silently', async ($, on) => {
    const host = installFakeHost(on, 'session-mine')
    await startSession($)
    host.failPlaylist()
    await host.clock.advance(3_000)
    expect(host.toasts.some(text => text.includes('could not open the playlist'))).toBe(true)
  })

  test('a failed playlist is loaded again once YouTube serves it, after a 30 s wait', async ($, on) => {
    const host = installFakeHost(on, 'session-mine')
    await startSession($)
    await $.turn.start({ text: 'long job', turnId: 'turn-1' })
    host.failPlaylist()
    await host.clock.advance(3_000)
    const ensuresAtFailure = host.ensureArgs.length

    await host.clock.advance(15_000)
    expect(host.ensureArgs.length).toBe(ensuresAtFailure)

    host.restorePlaylist()
    await host.clock.advance(18_000)
    expect(host.ensureArgs.length).toBeGreaterThan(ensuresAtFailure)
    expect(host.isMpvPlaying()).toBe(true)
  })
})

describe('pausing after a player error', () => {
  const openPermissionPrompt = ($: Engine) =>
    $.classic.PermissionRequest({ tool_name: 'Bash', tool_input: { command: 'rm -rf build' } })

  const playingSession = async ($: Engine, host: ReturnType<typeof installFakeHost>) => {
    await startSession($)
    await $.turn.start({ text: 'long job', turnId: 'turn-1' })
    await host.clock.advance(11_000)
    expect(host.isMpvPlaying()).toBe(true)
  }

  test('a transient player error does not stop a permission prompt from pausing', async ($, on) => {
    const host = installFakeHost(on, 'session-mine')
    await playingSession($, host)
    host.failNextRun('status')
    await host.clock.advance(3_000)

    await openPermissionPrompt($)
    expect(host.isMpvPlaying()).toBe(false)
  })

  test('while a failed load waits to retry, a permission prompt still pauses', async ($, on) => {
    const host = installFakeHost(on, 'session-mine')
    await playingSession($, host)
    host.failPlaylist()
    await host.clock.advance(3_000)

    await openPermissionPrompt($)
    expect(host.isMpvPlaying()).toBe(false)
  })
})

describe('play and pause overrides', () => {
  test('clearing a pause when a turn starts never rewrites the intent a --stop wrote', async ($, on) => {
    const host = installFakeHost(on, 'session-mine')
    await startSession($)
    const pane = await $.ui.mount({
      plugin: 'coding-tunes',
      surface: 'terminal',
      component: 'Pane',
      requestId: 'coding-tunes',
      props: PANE_PROPS,
    })
    await pane.press({ key: 'pause' })
    await host.clock.advance(0)
    expect(JSON.parse(host.files.get(`${SHARED_ROOT}/override.json`) ?? '""')).toBe('paused')
    await $.command.run({ command: 'coding-tunes', args: '--stop', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } })
    const intentWrites = () => host.writtenPaths.filter(path => path.endsWith('/intent.json')).length
    const writesAfterStop = intentWrites()

    await $.turn.start({ text: 'next job', turnId: 'turn-2' })
    await host.clock.advance(12_000)

    expect(intentWrites()).toBe(writesAfterStop)
    expect(JSON.parse(host.files.get(`${SHARED_ROOT}/intent.json`) ?? '{}').isEnabled).toBe(false)
    expect(JSON.parse(host.files.get(`${SHARED_ROOT}/override.json`) ?? '""')).toBe('none')
    expect(host.isMpvPlaying()).toBe(false)
    await pane.unmount()
  })
})

describe('session end', () => {
  const endSession = ($: Engine, reason: 'other' | 'clear') =>
    $.session.end({ reason, sessionId: 'session-mine', resume: { id: 'session-mine' } })
  const ownRecord = (host: ReturnType<typeof installFakeHost>) =>
    JSON.parse(host.files.get(`${SHARED_ROOT}/sessions/session-mine.json`) ?? '{}')

  test('the last session quits the player even when a tick lands while it ends', async ($, on) => {
    const host = installFakeHost(on, 'session-mine')
    await startSession($)
    await $.turn.start({ text: 'long job', turnId: 'turn-1' })
    await host.clock.advance(11_000)
    expect(host.isMpvPlaying()).toBe(true)

    const ending = endSession($, 'other')
    await host.clock.advance(3_000)
    await ending
    await host.clock.advance(6_000)

    expect(host.mpvCommands).toContain('quit')
    expect(ownRecord(host).hasEnded).toBe(true)
  })

  test('a /clear keeps the player running for the same process', async ($, on) => {
    const host = installFakeHost(on, 'session-mine')
    await startSession($)
    await endSession($, 'clear')
    await host.clock.advance(3_000)

    expect(host.mpvCommands).not.toContain('quit')
    expect(ownRecord(host).hasEnded).toBe(false)
  })
})

describe('shared player across sessions', () => {
  test("another session's pending question keeps the player paused and refuses play here", async ($, on) => {
    const host = installFakeHost(on, 'session-mine')
    await startSession($)
    writeForeignSession(host, 'session-other', 'question')

    await $.turn.start({ text: 'build it', turnId: 'turn-1' })
    await host.clock.advance(11_000)
    expect(host.isMpvPlaying()).toBe(false)

    const pane = await $.ui.mount({
      plugin: 'coding-tunes',
      surface: 'terminal',
      component: 'Pane',
      requestId: 'coding-tunes',
      props: PANE_PROPS,
    })
    expect(await pane.find({ type: 'Text', text: /"other#sess" awaits your input/ })).toBeDefined()
    await pane.press({ key: 'play' })
    await host.clock.advance(0)
    expect(host.isMpvPlaying()).toBe(false)
    expect(host.toasts.some(text => text.includes('waiting for your input'))).toBe(true)

    writeForeignSession(host, 'session-other', null)
    await host.clock.advance(3_000)
    expect(host.isMpvPlaying()).toBe(true)
    await pane.unmount()
  })
})
