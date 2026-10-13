import type { PlayerKind } from '../types'
import { PLAYER_KINDS, isPlayerKind } from './player-kind'

/** The pane's transport buttons, pressed by command. */
export type TransportAction = 'play' | 'pause' | 'next' | 'previous'

/** What `/coding-tunes <args>` asks for, before defaults are applied. */
export type TunesCommand =
  | { kind: 'start'; player?: PlayerKind; playlistId?: string }
  | { kind: 'control'; action: TransportAction }
  | { kind: 'pick' }
  | { kind: 'setup' }
  | { kind: 'stop' }
  | { kind: 'invalid'; reason: string }

type Flags = Map<string, string | true>

const TRANSPORT_FLAGS: Readonly<Record<string, TransportAction>> = {
  play: 'play',
  pause: 'pause',
  next: 'next',
  prev: 'previous',
  previous: 'previous',
}
const KNOWN_FLAGS = new Set(['player', 'list', 'playlist', 'setup', 'stop', ...Object.keys(TRANSPORT_FLAGS)])
const PLAYLIST_ID = /^[A-Za-z0-9_-]{2,128}$/

/**
 * Parses the text after `/coding-tunes`. Accepts `--flag=value` and
 * `--flag value`. Never throws: a bad flag or value is `{ kind: 'invalid' }`.
 */
export const parseTunesArgs = (args: string): TunesCommand => {
  const flags = readFlags(args.trim().split(/\s+/).filter(Boolean))
  if (typeof flags === 'string') return { kind: 'invalid', reason: flags }
  if (flags.size === 0) return { kind: 'pick' }
  if (flags.has('setup')) return { kind: 'setup' }
  if (flags.has('stop')) return { kind: 'stop' }
  const transport = [...flags.keys()].filter(flag => flag in TRANSPORT_FLAGS)
  if (transport.length > 0) return readTransport(flags, transport)

  return readStart(flags)
}

const readTransport = (flags: Flags, transport: readonly string[]): TunesCommand => {
  const [flag] = transport
  if (transport.length > 1 || flags.size > 1 || flag === undefined) {
    return { kind: 'invalid', reason: 'Use one of --play, --pause, --next or --prev, on its own.' }
  }
  if (flags.get(flag) !== true) return { kind: 'invalid', reason: `--${flag} takes no value.` }

  return { kind: 'control', action: TRANSPORT_FLAGS[flag] as TransportAction }
}

/**
 * Reads a playlist id from what the person typed: a bare id, a YouTube or
 * YouTube Music URL with `list=`, or a Spotify playlist URL or URI.
 */
export const extractPlaylistId = (text: string): string | undefined => {
  const trimmed = text.trim()
  const fromText =
    /[?&]list=([A-Za-z0-9_-]+)/.exec(trimmed)?.[1] ??
    /open\.spotify\.com\/playlist\/([A-Za-z0-9]+)/.exec(trimmed)?.[1] ??
    /^spotify:playlist:([A-Za-z0-9]+)$/.exec(trimmed)?.[1] ??
    trimmed

  return PLAYLIST_ID.test(fromText) ? fromText : undefined
}

const readFlags = (tokens: readonly string[]): Flags | string => {
  const flags: Flags = new Map()
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index] ?? ''
    const match = /^--([a-z]+)(?:=(.*))?$/.exec(token)
    if (match === null) return `Unexpected argument "${token}".`
    const [, name = '', inlineValue] = match
    if (!KNOWN_FLAGS.has(name)) return `Unknown flag --${name}.`
    const following = tokens[index + 1]
    const takesNext = inlineValue === undefined && following !== undefined && !following.startsWith('--')
    if (takesNext) index += 1
    flags.set(name, inlineValue ?? (takesNext ? following : true))
  }

  return flags
}

const readStart = (flags: Flags): TunesCommand => {
  const player = flags.get('player')
  const rawPlaylist = flags.get('list') ?? flags.get('playlist')
  if (player === true || rawPlaylist === true) {
    return { kind: 'invalid', reason: 'A flag is missing its value.' }
  }
  if (player !== undefined && !isPlayerKind(player)) {
    return { kind: 'invalid', reason: `Player must be one of ${PLAYER_KINDS.join(', ')}.` }
  }
  const playlistId = rawPlaylist === undefined ? undefined : extractPlaylistId(rawPlaylist)
  if (rawPlaylist !== undefined && playlistId === undefined) {
    return { kind: 'invalid', reason: `"${rawPlaylist}" is not a playlist id.` }
  }

  return { kind: 'start', player, playlistId }
}
