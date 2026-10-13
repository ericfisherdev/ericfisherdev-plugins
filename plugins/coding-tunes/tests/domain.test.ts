import { describe, expect, test } from 'claude-code/testing'

import { extractPlaylistId, parseTunesArgs } from '../hooks/command-args'
import { STALE_AFTER_MS, decidePlayback } from '../hooks/coordination'
import type { PlayerIntent, SessionRecord } from '../hooks/coordination'
import { SessionActivity } from '../hooks/session-activity'
import { clockText, marquee } from '../hooks/winamp-view'

const NOW = 1_000_000
const INTENT: PlayerIntent = { isEnabled: true, player: 'ytmusic', playlistId: 'PLabc', override: 'none' }

const record = (overrides: Partial<SessionRecord>): SessionRecord => ({
  sessionId: 'a',
  label: 'proj#aaaa',
  heartbeatAt: NOW,
  workingSince: null,
  holdReason: null,
  hasEnded: false,
  ...overrides,
})

describe('parseTunesArgs', () => {
  test('reads the player and the playlist in either flag form', () => {
    expect(parseTunesArgs('--player=ytmusic --list=PLQtABrboQ1MRguCL9d1Z7_v3owvB80vHY')).toEqual({
      kind: 'start',
      player: 'ytmusic',
      playlistId: 'PLQtABrboQ1MRguCL9d1Z7_v3owvB80vHY',
    })
    expect(parseTunesArgs('--player spotify --list 37i9dQZF1DX0XUsuxWHRQd')).toEqual({
      kind: 'start',
      player: 'spotify',
      playlistId: '37i9dQZF1DX0XUsuxWHRQd',
    })
  })

  test('bare asks, --setup sets up, --stop stops', () => {
    expect(parseTunesArgs('')).toEqual({ kind: 'pick' })
    expect(parseTunesArgs('--setup')).toEqual({ kind: 'setup' })
    expect(parseTunesArgs('--stop')).toEqual({ kind: 'stop' })
  })

  test('refuses an unknown player, flag or bare word', () => {
    expect(parseTunesArgs('--player=winamp').kind).toBe('invalid')
    expect(parseTunesArgs('--volume=11').kind).toBe('invalid')
    expect(parseTunesArgs('play').kind).toBe('invalid')
  })

  test('takes playlist links as well as ids', () => {
    expect(extractPlaylistId('https://music.youtube.com/playlist?list=PLabc_123')).toBe('PLabc_123')
    expect(extractPlaylistId('https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd?si=x')).toBe('37i9dQZF1DX0XUsuxWHRQd')
    expect(extractPlaylistId('spotify:playlist:37i9dQZF1DX0XUsuxWHRQd')).toBe('37i9dQZF1DX0XUsuxWHRQd')
    expect(extractPlaylistId('not a playlist')).toBeUndefined()
  })
})

describe('decidePlayback', () => {
  test('plays only once some session has worked for 10 seconds', () => {
    expect(decidePlayback(INTENT, [record({ workingSince: NOW - 9_000 })], NOW).shouldPlay).toBe(false)
    expect(decidePlayback(INTENT, [record({ workingSince: NOW - 10_000 })], NOW).shouldPlay).toBe(true)
  })

  test("any session's pending input holds the player paused, even against a forced play", () => {
    const records = [
      record({ sessionId: 'a', workingSince: NOW - 60_000 }),
      record({ sessionId: 'b', label: 'other#bbbb', holdReason: 'question' }),
    ]
    const decision = decidePlayback({ ...INTENT, override: 'playing' }, records, NOW)
    expect(decision.shouldPlay).toBe(false)
    expect(decision.holder?.label).toBe('other#bbbb')
  })

  test('a crashed session stops holding once its heartbeat goes stale', () => {
    const records = [
      record({ sessionId: 'a', workingSince: NOW - 60_000 }),
      record({ sessionId: 'dead', holdReason: 'permission', heartbeatAt: NOW - STALE_AFTER_MS - 1 }),
    ]
    expect(decidePlayback(INTENT, records, NOW)).toEqual({ shouldPlay: true, holder: null })
  })

  test('a paused override wins over work; no intent never plays', () => {
    const working = [record({ workingSince: NOW - 60_000 })]
    expect(decidePlayback({ ...INTENT, override: 'paused' }, working, NOW).shouldPlay).toBe(false)
    expect(decidePlayback(undefined, working, NOW).shouldPlay).toBe(false)
  })
})

describe('SessionActivity', () => {
  test('a permission prompt holds until every asked call settles', () => {
    const activity = new SessionActivity()
    activity.beginTurn(NOW)
    activity.markAsked('call-1')
    activity.markAsked('call-2')
    activity.openPermissionPrompt()
    expect(activity.holdReason()).toBe('permission')
    activity.settleToolCall('call-1')
    expect(activity.holdReason()).toBe('permission')
    activity.settleToolCall('call-2')
    expect(activity.holdReason()).toBeNull()
  })

  test('a question holds until answered, and the owner may waive it', () => {
    const activity = new SessionActivity()
    activity.openQuestion('q-1')
    expect(activity.holdReason()).toBe('question')
    activity.waiveHold()
    expect(activity.holdReason()).toBeNull()
    activity.openQuestion('q-2')
    expect(activity.holdReason()).toBe('question')
    activity.endTurn()
    expect(activity.holdReason()).toBeNull()
  })
})

describe('winamp view helpers', () => {
  test('the marquee scrolls by code point, never splitting a glyph', () => {
    const text = '🎵 Song title that is long'
    expect(marquee(text, 0, 5)).toBe('🎵 Son')
    expect(Array.from(marquee(text, 1, 5)).length).toBe(5)
    expect(marquee('short', 3, 10)).toBe('short')
  })

  test('the clock reads mm:ss', () => {
    expect(clockText(null)).toBe('--:--')
    expect(clockText(125)).toBe('02:05')
  })
})
