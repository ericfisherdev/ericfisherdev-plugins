import { cookieSpec } from '../browser-cookies'
import type { CookieSourceSetting } from '../browser-cookies'
import type { CommandRunner } from '../ports'
import { PlayerError } from './music-player'
import type { MusicPlayer, NowPlaying } from './music-player'

export type MpvPaths = {
  /** bin/mpvctl.py inside the plugin. */
  helper: string
  socket: string
  /** Serialises starting mpv so two sessions never start two players. */
  lock: string
}

const EXIT_NOT_RUNNING = 2
const EXIT_MISSING_DEPENDENCY = 3
const EXIT_BUSY = 5
const START_TIMEOUT_MS = 20_000

export const youTubeMusicPlaylistUrl = (playlistId: string): string =>
  `https://music.youtube.com/playlist?list=${encodeURIComponent(playlistId)}`

/**
 * YouTube Music through one detached mpv (with yt-dlp) shared by every
 * session, driven over its IPC socket by bin/mpvctl.py.
 */
export class MpvPlayer implements MusicPlayer {
  readonly kind = 'ytmusic' as const

  constructor(
    private readonly runner: CommandRunner,
    private readonly paths: MpvPaths,
    private readonly cookies: CookieSourceSetting,
  ) {}

  /** Rejects with PlayerError `missing-dependency` or `load-failed`. */
  async load(playlistId: string): Promise<void> {
    const url = youTubeMusicPlaylistUrl(playlistId)
    const source = await this.cookies.ytCookieSource()
    const argv = ['flock', this.paths.lock, ...this.helperArgv('ensure', url, source === null ? '' : cookieSpec(source))]
    const result = await this.runner.run(argv, START_TIMEOUT_MS)
    if (result.exitCode === EXIT_MISSING_DEPENDENCY) {
      throw new PlayerError('missing-dependency', `${result.stderr.trim()}: install mpv and yt-dlp with your package manager`)
    }
    if (result.exitCode === EXIT_BUSY) throw new PlayerError('load-failed', 'mpv is still loading the playlist; retrying shortly')
    if (result.exitCode !== 0) throw new PlayerError('load-failed', 'mpv did not start')
  }

  play = (): Promise<void> => this.control('play')
  pause = (): Promise<void> => this.control('pause')
  next = (): Promise<void> => this.control('next')
  previous = (): Promise<void> => this.control('prev')

  /** Rejects with PlayerError `load-failed` when YouTube refused the playlist. */
  async nowPlaying(): Promise<NowPlaying | null> {
    const result = await this.runner.run(this.helperArgv('status'))
    if (result.exitCode !== 0) return null
    const { hasFailed, ...playing } = JSON.parse(result.stdout) as NowPlaying & { hasFailed?: boolean }
    if (hasFailed === true) {
      throw new PlayerError('load-failed', 'YouTube could not open the playlist (private, deleted, a wrong id, or no network); retrying shortly')
    }

    return playing
  }

  async shutdown(): Promise<void> {
    await this.runner.run(this.helperArgv('quit'))
  }

  /** Rejects with PlayerError `unavailable` when mpv is not running or still loading. */
  private async control(command: string): Promise<void> {
    const result = await this.runner.run(this.helperArgv(command))
    if (result.exitCode === EXIT_NOT_RUNNING) throw new PlayerError('unavailable', 'mpv is not running')
    if (result.exitCode === EXIT_BUSY) throw new PlayerError('unavailable', 'mpv is still loading')
  }

  private helperArgv(...args: string[]): string[] {
    return ['python3', '-I', this.paths.helper, this.paths.socket, ...args]
  }
}
