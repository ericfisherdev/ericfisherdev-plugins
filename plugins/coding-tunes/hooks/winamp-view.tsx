import type { BoxProps, ButtonProps, ElementConstructor, RenderElement, TextProps } from 'claude-code'

import type { TunesSnapshot } from '../types'
import { PLAYER_LABELS } from './player-kind'

export type WinampElements = {
  Box: ElementConstructor<BoxProps>
  Text: ElementConstructor<TextProps>
  Button: ElementConstructor<ButtonProps>
}

export type WinampActions = {
  previous: () => void
  play: () => void
  pause: () => void
  next: () => void
}

/** Winamp 2's classic skin: charcoal body, blue title bar, green LCD on black. */
const SKIN = {
  body: '#2b2b3a',
  bevel: '#8c8ca3',
  titleBar: '#1b2a8a',
  titleText: '#f2d46b',
  lcd: '#000000',
  lcdText: '#00e600',
  lcdDim: '#007a00',
  amber: '#ffb000',
  alert: '#ff4040',
  barLow: '#00d000',
  barMid: '#e0e000',
  barHigh: '#ff3000',
} as const

const MAX_COLUMNS = 46
const MIN_COLUMNS = 24
const BAR_GLYPHS = Array.from(' ▁▂▃▄▅▆▇█')
const BAR_COUNT = 10

/** Draws the player; `columns` is the body width the pane offers. */
export const WinampView = (
  { Box, Text, Button }: WinampElements,
  snapshot: TunesSnapshot,
  columns: number,
  actions: WinampActions,
): RenderElement => {
  const width = Math.max(MIN_COLUMNS, Math.min(MAX_COLUMNS, columns))
  const inner = width - 4

  return (
    <Box flexDirection="column" width={width} borderStyle="single" borderColor={SKIN.bevel} backgroundColor={SKIN.body}>
      <Text backgroundColor={SKIN.titleBar} color={SKIN.titleText} bold wrap="truncate">
        {centered('▀▄▀ CODING TUNES ▀▄▀', width - 2)}
      </Text>
      <Box flexDirection="column" marginX={1} paddingX={1} backgroundColor={SKIN.lcd}>
        <Box flexDirection="row" justifyContent="space-between">
          <Text color={SKIN.lcdText} bold>
            {snapshot.isPlaying ? '▶' : '‖'} {clockText(snapshot.elapsedSeconds)}
          </Text>
          <Box flexDirection="row">{spectrum(Text, snapshot)}</Box>
        </Box>
        <Text color={SKIN.lcdText} wrap="truncate">
          {marquee(snapshot.track === '' ? idleTitle(snapshot) : snapshot.track, snapshot.frame, inner)}
        </Text>
        <Text color={SKIN.lcdDim} wrap="truncate">
          {snapshot.player === null ? 'NO PLAYER' : PLAYER_LABELS[snapshot.player].toUpperCase()}
          {'  PL '}
          {snapshot.playlistId ?? '--'}
        </Text>
      </Box>
      <Box flexDirection="row" justifyContent="center" gap={1}>
        <Button key="previous" label="|◀" hotkey="z" onPress={actions.previous} />
        <Button key="play" label="▶" hotkey="x" variant="primary" onPress={actions.play} />
        <Button key="pause" label="‖" hotkey="c" onPress={actions.pause} />
        <Button key="next" label="▶|" hotkey="b" onPress={actions.next} />
      </Box>
      {statusLine(Text, snapshot)}
    </Box>
  )
}

const statusLine = (Text: WinampElements['Text'], snapshot: TunesSnapshot): RenderElement | null => {
  if (snapshot.notice !== null) {
    return <Text key="notice" color={SKIN.alert} wrap="truncate">{snapshot.notice}</Text>
  }
  if (snapshot.heldBy !== null) {
    const who = snapshot.isHeldHere ? 'this session' : `"${snapshot.heldBy}"`
    return <Text key="held" color={SKIN.amber} wrap="truncate">PAUSED: {who} awaits your input</Text>
  }

  return null
}

const spectrum = (Text: WinampElements['Text'], snapshot: TunesSnapshot): RenderElement[] =>
  barHeights(snapshot).map((height, index) => (
    <Text key={`bar${index}`} color={height > 6 ? SKIN.barHigh : height > 3 ? SKIN.barMid : SKIN.barLow}>
      {BAR_GLYPHS[height] ?? ' '}
    </Text>
  ))

/** Pseudo-random bar heights from the frame; flat while paused. */
export const barHeights = (snapshot: TunesSnapshot): number[] =>
  Array.from({ length: BAR_COUNT }, (_, index) => {
    if (!snapshot.isPlaying) return 1
    const seed = Math.sin((snapshot.frame + 1) * 12.9898 + index * 78.233) * 43758.5453
    const noise = seed - Math.floor(seed)
    const falloff = 1 - index / (BAR_COUNT * 1.6)

    return Math.max(1, Math.round(noise * 8 * falloff))
  })

/** Scrolls `text` one step per frame through a window of `width` code points. */
export const marquee = (text: string, frame: number, width: number): string => {
  const glyphs = Array.from(text)
  if (glyphs.length <= width) return text
  const loop = [...glyphs, ...Array.from(' *** ')]
  const start = frame % loop.length

  return [...loop, ...loop].slice(start, start + width).join('')
}

export const clockText = (seconds: number | null): string => {
  if (seconds === null) return '--:--'
  const minutes = Math.floor(seconds / 60)

  return `${String(minutes).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

const idleTitle = (snapshot: TunesSnapshot): string =>
  snapshot.player === null ? 'Run /coding-tunes to load a playlist' : 'Waiting for Claude to get to work...'

const centered = (text: string, width: number): string => {
  const length = Array.from(text).length
  const left = Math.max(0, Math.floor((width - length) / 2))

  return `${' '.repeat(left)}${text}`.padEnd(width, ' ')
}
