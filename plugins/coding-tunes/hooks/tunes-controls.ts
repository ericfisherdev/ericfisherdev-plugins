import type { PlayerKind } from '../types'
import type { PlaybackOverride, SharedBoard } from './coordination'
import type { PlayerRegistry } from './players/music-player'
import type { PlaybackSync, SessionIdentity } from './playback-sync'
import type { SessionActivity } from './session-activity'

/** What a control did: done, or refused with the reason to show. */
export type ControlOutcome = { isDone: true } | { isDone: false; reason: string }

const DONE: ControlOutcome = { isDone: true }

/**
 * The person's controls over the shared player: start, stop, play, pause,
 * next, previous. Play respects another session's hold: only the session
 * awaiting input may resume while it waits.
 */
export class TunesControls {
  constructor(
    private readonly board: SharedBoard,
    private readonly activity: SessionActivity,
    private readonly players: PlayerRegistry,
    private readonly sync: PlaybackSync,
    private readonly identity: SessionIdentity,
  ) {}

  async start(player: PlayerKind, playlistId: string): Promise<ControlOutcome> {
    const previous = await this.board.readIntent()
    if (previous?.isEnabled === true && previous.player !== player) await this.players[previous.player].shutdown()
    await this.board.writeIntent({ isEnabled: true, player, playlistId })
    await this.board.writeOverride('none')
    this.sync.forceReload()
    await this.sync.reconcile()

    return DONE
  }

  /** Reloads the current playlist, so a changed browser login takes effect. */
  async reload(): Promise<void> {
    const intent = await this.board.readIntent()
    if (intent === undefined || !intent.isEnabled) return
    this.sync.forceReload()
    await this.sync.reconcile()
  }

  async stop(): Promise<ControlOutcome> {
    const intent = await this.board.readIntent()
    if (intent === undefined || !intent.isEnabled) return { isDone: false, reason: 'Nothing is playing.' }
    await this.board.writeIntent({ ...intent, isEnabled: false })
    await this.players[intent.player].shutdown()
    await this.sync.reconcile()

    return DONE
  }

  /** Refused while another session waits on the person's input. */
  async play(): Promise<ControlOutcome> {
    const { holder } = await this.sync.currentDecision()
    if (holder !== null && holder.sessionId !== this.identity.sessionId) {
      return { isDone: false, reason: `Paused: session "${holder.label}" is waiting for your input.` }
    }
    if (holder !== null) this.activity.waiveHold()

    return this.setOverride('playing')
  }

  pause(): Promise<ControlOutcome> {
    return this.setOverride('paused')
  }

  next(): Promise<ControlOutcome> {
    return this.skip(player => player.next())
  }

  previous(): Promise<ControlOutcome> {
    return this.skip(player => player.previous())
  }

  /** A pause lasts until a turn starts; a forced play until a turn ends. */
  async clearOverride(expired: PlaybackOverride): Promise<void> {
    if ((await this.board.readOverride()) !== expired) return
    await this.board.writeOverride('none')
  }

  private async setOverride(override: PlaybackOverride): Promise<ControlOutcome> {
    const intent = await this.board.readIntent()
    if (intent === undefined || !intent.isEnabled) return { isDone: false, reason: 'Start a playlist with /coding-tunes first.' }
    await this.board.writeOverride(override)
    await this.sync.reconcile()

    return DONE
  }

  private async skip(move: (player: PlayerRegistry[PlayerKind]) => Promise<void>): Promise<ControlOutcome> {
    const intent = await this.board.readIntent()
    if (intent === undefined || !intent.isEnabled) return { isDone: false, reason: 'Start a playlist with /coding-tunes first.' }
    await move(this.players[intent.player])
    await this.sync.reconcile()

    return DONE
  }
}
