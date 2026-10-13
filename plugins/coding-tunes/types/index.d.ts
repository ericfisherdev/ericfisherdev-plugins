/** Which music service drives playback. */
export type PlayerKind = 'ytmusic' | 'spotify'

/** What the Winamp pane draws: the shared player as this session last saw it. */
export type TunesSnapshot = {
  player: PlayerKind | null
  playlistId: string | null
  track: string
  isPlaying: boolean
  elapsedSeconds: number | null
  /** Label of the session whose pending input holds the player paused, if any. */
  heldBy: string | null
  /** True when this session itself is the one holding the player. */
  isHeldHere: boolean
  /** Last problem worth showing on the LCD (missing yt-dlp, no Spotify device). */
  notice: string | null
  /** Animation step for the marquee and spectrum. */
  frame: number
}

declare module 'claude-code' {
  interface PluginState {
    'coding-tunes': { snapshot: TunesSnapshot }
  }
}
