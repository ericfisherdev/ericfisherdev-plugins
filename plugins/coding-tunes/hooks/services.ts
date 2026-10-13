import type { PlayerKind } from '../types'
import { BrowserCookieFinder } from './browser-cookies'
import { SharedBoard } from './coordination'
import { MpvPlayer } from './players/mpv-player'
import type { PlayerRegistry } from './players/music-player'
import { SpotifyAuth, XdgLoginBrowser } from './players/spotify-auth'
import { SpotifyPlayer } from './players/spotify-player'
import { PlaybackSync } from './playback-sync'
import type { SessionIdentity } from './playback-sync'
import type { CommandRunner, HostPorts } from './ports'
import { SessionActivity } from './session-activity'
import { TunesCommandFlow } from './tunes-command'
import type { DependencyCheck } from './tunes-command'
import { TunesControls } from './tunes-controls'
import { TunesPreferences } from './tunes-preferences'

export type TunesServices = {
  activity: SessionActivity
  board: SharedBoard
  sync: PlaybackSync
  controls: TunesControls
  flow: TunesCommandFlow
}

/** Wires every collaborator for one session from the host's ports. */
export const buildServices = (host: HostPorts, cwd: string): TunesServices => {
  const sharedRoot = `${host.runtimeDir}/coding-tunes`
  const board = new SharedBoard(host.files, sharedRoot)
  const auth = new SpotifyAuth(host.http, host.store, host.clock)
  const preferences = new TunesPreferences(host.store)
  const players: PlayerRegistry = {
    ytmusic: new MpvPlayer(host.runner, {
      helper: `${host.pluginRoot}/bin/mpvctl.py`,
      socket: `${sharedRoot}/mpv.sock`,
      lock: `${sharedRoot}/mpv.lock`,
    }, preferences),
    spotify: new SpotifyPlayer(host.http, auth),
  }
  const identity = sessionIdentity(host.sessionId, cwd)
  const activity = new SessionActivity()
  const sync = new PlaybackSync(board, activity, players, host.clock, identity, host.snapshots, host.notifier)
  const controls = new TunesControls(board, activity, players, sync, identity)
  const browser = new XdgLoginBrowser(host.runner, `${host.pluginRoot}/bin/oauth_callback.py`, url =>
    host.notifier.log(`Coding Tunes: if no browser opened, open this page to link Spotify: ${url}`),
  )
  const flow = new TunesCommandFlow(
    controls,
    preferences,
    host.prompter,
    { link: clientId => auth.authorize(clientId, browser) },
    dependencyCheck(host.runner, auth),
    new BrowserCookieFinder(host.localFiles, host.homeDir),
  )

  return { activity, board, sync, controls, flow }
}

/**
 * The per-user folder the shared player lives in: $XDG_RUNTIME_DIR, else
 * ~/.cache, else the plugin's own folder. Never a world-writable one such as
 * /tmp, where another local user could plant the socket or the records first.
 */
export const resolveRuntimeDir = (xdgRuntimeDir: string | undefined, homeDir: string, pluginRoot: string): string => {
  if (xdgRuntimeDir !== undefined && xdgRuntimeDir !== '') return xdgRuntimeDir

  return homeDir === '' ? `${pluginRoot}/.run` : `${homeDir}/.cache`
}

/** Sessions show each other as `<folder>#<id prefix>`. */
export const sessionIdentity = (sessionId: string, cwd: string): SessionIdentity => {
  const folder = cwd.split('/').filter(Boolean).at(-1) ?? 'session'

  return { sessionId, label: `${folder}#${sessionId.slice(0, 4)}` }
}

const dependencyCheck = (runner: CommandRunner, auth: SpotifyAuth): DependencyCheck => ({
  missingFor: async (player: PlayerKind) => {
    if (player === 'spotify') {
      return auth.accessToken().then(
        () => undefined,
        () => 'Spotify is not linked yet: run /coding-tunes --setup and choose Spotify.',
      )
    }
    const missing = await missingTools(runner, ['mpv', 'yt-dlp'])

    return missing.length === 0 ? undefined : `YouTube Music needs ${missing.join(' and ')}: install ${missing.join(' and ')} with your package manager`
  },
})

const missingTools = async (runner: CommandRunner, tools: readonly string[]): Promise<string[]> => {
  const found = await Promise.all(
    tools.map(tool => runner.run(['which', tool]).then(result => result.exitCode === 0, () => false)),
  )

  return tools.filter((_, index) => !found[index])
}
