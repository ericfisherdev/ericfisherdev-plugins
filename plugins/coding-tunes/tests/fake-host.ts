import type { On } from 'claude-code'
import { mock } from 'claude-code/testing'
import type { MockClock } from 'claude-code/testing'

export const RUNTIME_DIR = '/run/test'
export const SHARED_ROOT = `${RUNTIME_DIR}/coding-tunes`
export const START_TIME = 5_000_000

/** The machine beneath the mod: an in-memory file system, a fake mpv, toasts. */
export type FakeHost = {
  clock: MockClock
  files: Map<string, string>
  /** Every path written, in order. */
  writtenPaths: string[]
  /** Every mpvctl command sent, in order (`ensure`, `play`, `pause`, ...). */
  mpvCommands: string[]
  /** The arguments after `ensure`: the playlist URL and the cookie spec. */
  ensureArgs: string[][]
  toasts: string[]
  isMpvPlaying: () => boolean
  /** Makes YouTube refuse the playlist: mpv reports the failure until it is restored. */
  failPlaylist: () => void
  /** Makes YouTube serve the playlist again; the next `ensure` reloads it. */
  restorePlaylist: () => void
}

export const installFakeHost = (on: On, sessionId: string, storeEntries: Readonly<Record<string, unknown>> = {}): FakeHost => {
  const clock = mock.clock(on, { now: START_TIME })
  mock.store(on, storeEntries)
  mock.env(on, { XDG_RUNTIME_DIR: RUNTIME_DIR })
  const files = new Map<string, string>()
  const writtenPaths: string[] = []
  const mpvCommands: string[] = []
  const ensureArgs: string[][] = []
  const toasts: string[] = []
  let isPlaying = false
  let hasFailed = false
  let isPlaylistRefused = false

  on('session.id', () => ({ value: sessionId }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('session.end', ($, e) => ({ sessionId: e.sessionId }))
  on('turn.start', ($, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('ui.open', () => ({ value: { isPlaced: true as const } }))
  on('ui.toast', ($, e) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  on('ui.log', () => ({ value: undefined }))

  on('fs.write', ($, e) => {
    files.set(e.path, e.text)
    writtenPaths.push(e.path)
    return { value: undefined }
  })
  on('fs.read', ($, e) => {
    const text = files.get(e.path)
    return text === undefined ? { deny: `ENOENT: ${e.path}` } : { value: text }
  })
  on('fs.list', ($, e) => ({
    value: [...files.keys()]
      .filter(path => path.startsWith(`${e.path}/`) && !path.slice(e.path.length + 1).includes('/'))
      .map(path => ({ name: path.slice(e.path.length + 1), kind: 'file' as const, size: 0, mtimeMs: 0, isLink: false })),
  }))

  on('process.run', ($, e) => {
    const helperAt = e.argv.findIndex(arg => arg.endsWith('mpvctl.py'))
    const command = helperAt < 0 ? '' : (e.argv[helperAt + 2] ?? '')
    if (command !== '' && command !== 'status') mpvCommands.push(command)
    if (command === 'ensure') {
      ensureArgs.push(e.argv.slice(helperAt + 3))
      hasFailed = isPlaylistRefused
    }
    if (command === 'play') isPlaying = true
    if (command === 'pause') isPlaying = false
    const stdout = command === 'status' ? JSON.stringify({ track: 'Llama Song', isPlaying, elapsedSeconds: 42, hasFailed }) : ''

    return { value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })

  return { clock, files, writtenPaths, mpvCommands, ensureArgs, toasts, isMpvPlaying: () => isPlaying, failPlaylist: () => {
      isPlaylistRefused = true
      hasFailed = true
    },
    restorePlaylist: () => void (isPlaylistRefused = false),
  }
}

/** Another session's record, as that session's own mod would write it. */
export const writeForeignSession = (host: FakeHost, sessionId: string, holdReason: 'question' | 'permission' | null): void => {
  host.files.set(
    `${SHARED_ROOT}/sessions/${sessionId}.json`,
    JSON.stringify({
      sessionId,
      label: `other#${sessionId.slice(0, 4)}`,
      heartbeatAt: host.clock.now(),
      workingSince: null,
      holdReason,
      hasEnded: false,
    }),
  )
}
