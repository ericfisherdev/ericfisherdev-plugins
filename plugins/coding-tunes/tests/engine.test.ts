import { describe, expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'

import { installFakeHost, writeForeignSession } from './fake-host'

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
