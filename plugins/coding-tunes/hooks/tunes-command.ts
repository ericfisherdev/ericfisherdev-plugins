import type { PlayerKind } from '../types'
import type { YtCookieSource } from './browser-cookies'
import { extractPlaylistId, parseTunesArgs } from './command-args'
import { PLAYER_KINDS, PLAYER_LABELS, playerKindFromLabel } from './player-kind'
import type { TunesControls } from './tunes-controls'
import type { Prompter } from './ports'
import type { TunesPreferences } from './tunes-preferences'

/** Links the Spotify account. Rejects with PlayerError `not-authorized` on failure. */
export interface SpotifyLinker {
  link(clientId: string): Promise<void>
}

/** Lists the browser logins yt-dlp could sign YouTube requests with. */
export interface CookieSourceFinder {
  find(): Promise<YtCookieSource[]>
}

/** Says what is missing for a player to work, or nothing. */
export interface DependencyCheck {
  missingFor(player: PlayerKind): Promise<string | undefined>
}

const SAMPLE_PLAYLISTS: Readonly<Record<PlayerKind, readonly string[]>> = {
  ytmusic: ['PLQtABrboQ1MRguCL9d1Z7_v3owvB80vHY'],
  spotify: [],
}
const PASTE_HINT = 'Paste an id or link under "Other"'
const KEEP_CLIENT = 'Keep the saved client id'
const SKIP_LOGIN = 'Skip Spotify login'
const NO_BROWSER_LOGIN = 'No browser login (public playlists only)'
const MAX_BROWSER_OPTIONS = 3

/** Answers `/coding-tunes [args]` with the text to print. */
export class TunesCommandFlow {
  constructor(
    private readonly controls: TunesControls,
    private readonly preferences: TunesPreferences,
    private readonly prompter: Prompter,
    private readonly spotify: SpotifyLinker,
    private readonly dependencies: DependencyCheck,
    private readonly browsers: CookieSourceFinder,
  ) {}

  async run(args: string): Promise<string> {
    const command = parseTunesArgs(args)
    try {
      switch (command.kind) {
        case 'invalid':
          return `${command.reason} Usage: /coding-tunes [--player=ytmusic|spotify] [--list=<playlist id>] | --setup | --stop`
        case 'setup':
          return await this.setup()
        case 'stop':
          return outcomeText(await this.controls.stop(), 'Coding Tunes stopped.')
        case 'pick':
          return await this.startWith(undefined, undefined)
        case 'start':
          return await this.startWith(command.player, command.playlistId)
      }
    } catch (error) {
      return error instanceof Error ? error.message : String(error)
    }
  }

  private async startWith(player: PlayerKind | undefined, playlistId: string | undefined): Promise<string> {
    const defaults = await this.preferences.defaults()
    const isBare = player === undefined && playlistId === undefined
    const chosenPlayer = player ?? (isBare ? await this.askPlayer() : defaults?.player) ?? (await this.askPlayer())
    const fallbackPlaylist = !isBare && defaults?.player === chosenPlayer ? defaults.playlistId : undefined
    const chosenPlaylist = playlistId ?? fallbackPlaylist ?? (await this.askPlaylist(chosenPlayer))
    const missing = await this.dependencies.missingFor(chosenPlayer)
    if (missing !== undefined) return missing
    await this.preferences.rememberPlaylist(chosenPlayer, chosenPlaylist)
    const outcome = await this.controls.start(chosenPlayer, chosenPlaylist)

    return outcomeText(outcome, `${PLAYER_LABELS[chosenPlayer]} playlist ${chosenPlaylist} is loaded. It plays once Claude has worked for 10 seconds.`)
  }

  private async setup(): Promise<string> {
    const player = await this.askPlayer('Which player should /coding-tunes use by default?')
    const playlistId = await this.askPlaylist(player)
    await this.preferences.saveDefaults({ player, playlistId })
    const lines = [`Defaults saved: ${PLAYER_LABELS[player]}, playlist ${playlistId}.`]
    lines.push(player === 'spotify' ? await this.linkSpotify() : await this.chooseBrowserLogin())
    const missing = await this.dependencies.missingFor(player)
    if (missing !== undefined) lines.push(missing)

    return lines.join('\n')
  }

  /** Lets YouTube Music open private playlists with a browser's signed-in cookies. */
  private async chooseBrowserLogin(): Promise<string> {
    const sources = (await this.browsers.find()).slice(0, MAX_BROWSER_OPTIONS)
    if (sources.length === 0) return 'No browser login found: only public playlists will open.'
    const answer = await this.prompter.ask(
      'Use the YouTube login from which browser? It lets private playlists play.',
      [...sources.map(source => source.label), NO_BROWSER_LOGIN],
    )
    const chosen = sources.find(source => source.label === answer) ?? null
    await this.preferences.saveYtCookieSource(chosen)
    await this.controls.reload()
    if (chosen === null) return 'Browser login off: only public playlists will open.'
    const keyringNote = chosen.browser === 'firefox' ? '' : ' Reading its cookies may ask you to unlock your keyring.'

    return `YouTube Music now signs in with your ${chosen.label} login.${keyringNote}`
  }

  private async linkSpotify(): Promise<string> {
    const saved = await this.preferences.spotifyClientId()
    const options = saved === undefined ? [SKIP_LOGIN, PASTE_HINT] : [KEEP_CLIENT, SKIP_LOGIN]
    const answer = await this.prompter.ask(
      'Spotify client id? Create an app at developer.spotify.com with redirect URI http://127.0.0.1:8898/callback, then paste its client id under "Other".',
      options,
    )
    if (answer === SKIP_LOGIN || answer === PASTE_HINT) return 'Spotify login skipped.'
    const clientId = answer === KEEP_CLIENT && saved !== undefined ? saved : answer.trim()
    if (!/^[A-Za-z0-9]{16,64}$/.test(clientId)) return `"${clientId}" is not a Spotify client id; login skipped.`
    await this.preferences.saveSpotifyClientId(clientId)
    await this.spotify.link(clientId)

    return 'Spotify linked.'
  }

  private async askPlayer(question = 'Which player should Coding Tunes use?'): Promise<PlayerKind> {
    const answer = await this.prompter.ask(question, PLAYER_KINDS.map(kind => PLAYER_LABELS[kind]))
    const player = playerKindFromLabel(answer)
    if (player === undefined) throw new Error(`"${answer}" is not a player.`)

    return player
  }

  private async askPlaylist(player: PlayerKind): Promise<string> {
    const known = [...new Set([...(await this.preferences.recentPlaylists(player)), ...SAMPLE_PLAYLISTS[player]])]
    const options = [...known.slice(0, 3), PASTE_HINT].slice(0, 4)
    const padded = options.length < 2 ? [...options, 'Cancel'] : options
    const answer = await this.prompter.ask(`Which ${PLAYER_LABELS[player]} playlist? (id or link)`, padded)
    const playlistId = extractPlaylistId(answer)
    if (playlistId === undefined || answer === PASTE_HINT || answer === 'Cancel') throw new Error('No playlist chosen.')

    return playlistId
  }
}

const outcomeText = (outcome: { isDone: true } | { isDone: false; reason: string }, done: string): string =>
  outcome.isDone ? done : outcome.reason
