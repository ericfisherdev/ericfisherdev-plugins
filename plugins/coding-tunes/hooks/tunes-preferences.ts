import type { PlayerKind } from '../types'
import type { CookieSourceSetting, YtCookieSource } from './browser-cookies'
import type { KeyValueStore } from './ports'

export type TunesDefaults = { player: PlayerKind; playlistId: string }

const DEFAULTS_KEY = 'defaults'
const RECENT_KEY = 'recentPlaylists'
const CLIENT_ID_KEY = 'spotifyClientId'
const COOKIE_SOURCE_KEY = 'ytCookieSource'
const RECENT_LIMIT = 3

/** The person's saved choices, kept across sessions in the plugin store. */
export class TunesPreferences implements CookieSourceSetting {
  constructor(private readonly store: KeyValueStore) {}

  async defaults(): Promise<TunesDefaults | undefined> {
    return (await this.store.get(DEFAULTS_KEY)) as TunesDefaults | undefined
  }

  async saveDefaults(defaults: TunesDefaults): Promise<void> {
    await this.store.set(DEFAULTS_KEY, defaults)
  }

  async recentPlaylists(player: PlayerKind): Promise<string[]> {
    const recent = ((await this.store.get(RECENT_KEY)) ?? {}) as Partial<Record<PlayerKind, string[]>>

    return recent[player] ?? []
  }

  async rememberPlaylist(player: PlayerKind, playlistId: string): Promise<void> {
    const recent = ((await this.store.get(RECENT_KEY)) ?? {}) as Partial<Record<PlayerKind, string[]>>
    const list = [playlistId, ...(recent[player] ?? []).filter(id => id !== playlistId)].slice(0, RECENT_LIMIT)
    await this.store.set(RECENT_KEY, { ...recent, [player]: list })
  }

  async spotifyClientId(): Promise<string | undefined> {
    return (await this.store.get(CLIENT_ID_KEY)) as string | undefined
  }

  async saveSpotifyClientId(clientId: string): Promise<void> {
    await this.store.set(CLIENT_ID_KEY, clientId)
  }

  /** The browser login YouTube Music requests use; null for none. */
  async ytCookieSource(): Promise<YtCookieSource | null> {
    return ((await this.store.get(COOKIE_SOURCE_KEY)) ?? null) as YtCookieSource | null
  }

  async saveYtCookieSource(source: YtCookieSource | null): Promise<void> {
    await this.store.set(COOKIE_SOURCE_KEY, source)
  }
}
