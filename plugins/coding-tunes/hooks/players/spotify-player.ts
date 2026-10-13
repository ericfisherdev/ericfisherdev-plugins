import type { HttpClient, HttpReply } from '../ports'
import { PlayerError } from './music-player'
import type { MusicPlayer, NowPlaying } from './music-player'
import type { AccessTokenSource } from './spotify-auth'

const API = 'https://api.spotify.com/v1/me/player'

type PlaybackState = {
  is_playing: boolean
  progress_ms: number | null
  context: { uri: string } | null
  item: { name: string; artists?: { name: string }[] } | null
}

/**
 * Spotify through the Web API, playing on whichever Spotify client the
 * account has active (Premium only). The account itself is the shared player.
 */
export class SpotifyPlayer implements MusicPlayer {
  readonly kind = 'spotify' as const
  private contextUri: string | null = null

  constructor(
    private readonly http: HttpClient,
    private readonly tokens: AccessTokenSource,
  ) {}

  async load(playlistId: string): Promise<void> {
    this.contextUri = `spotify:playlist:${playlistId}`
  }

  /** Starts the loaded playlist, or resumes it when it is already the context. */
  async play(): Promise<void> {
    const state = await this.state()
    const isLoaded = this.contextUri === null || state?.context?.uri === this.contextUri
    const body = isLoaded ? undefined : JSON.stringify({ context_uri: this.contextUri })
    await this.send('PUT', '/play', body)
  }

  async pause(): Promise<void> {
    const state = await this.state()
    if (state?.is_playing === true) await this.send('PUT', '/pause')
  }

  next = (): Promise<void> => this.send('POST', '/next')
  previous = (): Promise<void> => this.send('POST', '/previous')

  async nowPlaying(): Promise<NowPlaying | null> {
    const state = await this.state()
    if (state === null || state.item === null) return null
    const artists = (state.item.artists ?? []).map(artist => artist.name).join(', ')

    return {
      track: artists === '' ? state.item.name : `${artists} - ${state.item.name}`,
      isPlaying: state.is_playing,
      elapsedSeconds: state.progress_ms === null ? null : Math.floor(state.progress_ms / 1000),
    }
  }

  async shutdown(): Promise<void> {
    await this.pause()
  }

  private async state(): Promise<PlaybackState | null> {
    const reply = await this.call('GET', '')

    return reply.status === 204 || reply.text === '' ? null : (JSON.parse(reply.text) as PlaybackState)
  }

  private async send(method: string, path: string, body?: string): Promise<void> {
    await this.call(method, path, body)
  }

  /** Rejects with PlayerError `not-authorized`, `premium-required`, `no-device` or `unavailable`. */
  private async call(method: string, path: string, body?: string): Promise<HttpReply> {
    const headers: Record<string, string> = { Authorization: `Bearer ${await this.tokens.accessToken()}` }
    if (body !== undefined) headers['Content-Type'] = 'application/json'
    const reply = await this.http.request(`${API}${path}`, { method, headers, body })
    if (reply.ok) return reply
    throw failureFor(reply)
  }
}

const failureFor = (reply: HttpReply): PlayerError => {
  if (reply.status === 401) return new PlayerError('not-authorized', 'Spotify login expired: run /coding-tunes --setup')
  if (reply.status === 404) return new PlayerError('no-device', 'No Spotify device: open Spotify somewhere')
  if (reply.status === 403) return new PlayerError('premium-required', 'Spotify playback control needs Premium')

  return new PlayerError('unavailable', `Spotify answered ${reply.status}`)
}
