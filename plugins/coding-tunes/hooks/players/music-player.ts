import type { PlayerKind } from '../../types'

export type NowPlaying = {
  track: string
  isPlaying: boolean
  elapsedSeconds: number | null
}

/** Why a player could not do what was asked. */
export type PlayerFailure =
  | 'missing-dependency'
  | 'not-authorized'
  | 'premium-required'
  | 'no-device'
  | 'unavailable'

export class PlayerError extends Error {
  constructor(
    readonly failure: PlayerFailure,
    message: string,
  ) {
    super(message)
    this.name = 'PlayerError'
  }
}

/**
 * One music service's controls. Every method may reject with PlayerError:
 * `missing-dependency` (mpv or yt-dlp absent), `not-authorized` (no or
 * expired Spotify login), `premium-required`, `no-device` (no open Spotify
 * client), `unavailable` (the player did not answer).
 */
export interface MusicPlayer {
  readonly kind: PlayerKind
  /** Makes `playlistId` the loaded playlist, paused, starting the player if needed. */
  load(playlistId: string): Promise<void>
  play(): Promise<void>
  pause(): Promise<void>
  next(): Promise<void>
  previous(): Promise<void>
  /** Resolves null when nothing is loaded. */
  nowPlaying(): Promise<NowPlaying | null>
  /** Stops the shared player; called when the last session ends or on --stop. */
  shutdown(): Promise<void>
}

export type PlayerRegistry = Readonly<Record<PlayerKind, MusicPlayer>>
