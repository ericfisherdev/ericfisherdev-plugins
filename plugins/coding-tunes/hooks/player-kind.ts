import type { PlayerKind } from '../types'

export const PLAYER_KINDS: readonly PlayerKind[] = ['ytmusic', 'spotify']

export const PLAYER_LABELS: Readonly<Record<PlayerKind, string>> = {
  ytmusic: 'YouTube Music',
  spotify: 'Spotify',
}

export const isPlayerKind = (value: string): value is PlayerKind =>
  (PLAYER_KINDS as readonly string[]).includes(value)

export const playerKindFromLabel = (label: string): PlayerKind | undefined =>
  PLAYER_KINDS.find(kind => PLAYER_LABELS[kind] === label)
