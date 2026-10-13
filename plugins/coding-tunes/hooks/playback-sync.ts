import { decidePlayback, liveRecords } from './coordination'
import type { PlaybackDecision, PlayerIntent, SharedBoard } from './coordination'
import { PlayerError } from './players/music-player'
import type { MusicPlayer, NowPlaying, PlayerRegistry } from './players/music-player'
import type { Clock, Notifier, SnapshotSink } from './ports'
import type { SessionActivity } from './session-activity'

export type SessionIdentity = { sessionId: string; label: string }

/** How long a failed load waits before the player is asked to load again. */
export const LOAD_RETRY_MS = 30_000

/**
 * Keeps the shared player in step with every session's activity: publishes
 * this session's record, applies the shared play/pause rule on each change of
 * decision, and refreshes the pane. Calls are serialised.
 */
export class PlaybackSync {
  private queue: Promise<void> = Promise.resolve()
  private loadedKey: string | null = null
  private appliedDecision: boolean | null = null
  private lastNotice: string | null = null
  private retryLoadAt = 0
  private hasEnded = false
  private frame = 0

  constructor(
    private readonly board: SharedBoard,
    private readonly activity: SessionActivity,
    private readonly players: PlayerRegistry,
    private readonly clock: Clock,
    private readonly identity: SessionIdentity,
    private readonly sink: SnapshotSink,
    private readonly notifier: Notifier,
  ) {}

  /** Runs one sync after any already queued; never rejects. A no-op once ended. */
  reconcile(): Promise<void> {
    this.queue = this.queue
      .then(() => (this.hasEnded ? undefined : this.syncOnce()))
      .catch(error => this.report(error))

    return this.queue
  }

  /** Forgets what was loaded and applied, so the next sync loads and decides afresh. */
  forceReload(): void {
    this.loadedKey = null
    this.appliedDecision = null
    this.retryLoadAt = 0
  }

  /** The current decision, for user controls that must respect holds. */
  async currentDecision(): Promise<PlaybackDecision> {
    const now = await this.clock.now()

    return decidePlayback(await this.board.readIntent(), await this.board.readOverride(), await this.board.records(), now)
  }

  /**
   * Marks this session ended, after any queued sync and before none: later
   * reconciles do nothing, so no tick can republish this session as live.
   * The last live session shuts the player down.
   */
  end(): Promise<void> {
    const ending = this.queue.then(() => this.endOnce())
    this.hasEnded = true
    this.queue = ending.catch(() => undefined)

    return ending
  }

  private async endOnce(): Promise<void> {
    const now = await this.clock.now()
    await this.board.publish({ ...this.activity.toRecord(this.identity.sessionId, this.identity.label, now), hasEnded: true })
    const others = liveRecords(await this.board.records(), now).filter(
      record => record.sessionId !== this.identity.sessionId,
    )
    const intent = await this.board.readIntent()
    if (others.length === 0 && intent?.isEnabled === true) await this.players[intent.player].shutdown()
  }

  private async syncOnce(): Promise<void> {
    const now = await this.clock.now()
    await this.board.publish(this.activity.toRecord(this.identity.sessionId, this.identity.label, now))
    const records = await this.board.records()
    const intent = await this.board.readIntent()
    const decision = decidePlayback(intent, await this.board.readOverride(), records, now)
    const isWaitingToRetry = this.loadedKey === null && now < this.retryLoadAt
    const playing = intent?.isEnabled === true && !isWaitingToRetry ? await this.drive(intent, decision) : null
    await this.board.prune(records, now)
    await this.showSnapshot(intent, decision, playing, isWaitingToRetry ? this.lastNotice : null)
  }

  private async drive(intent: PlayerIntent, decision: PlaybackDecision): Promise<NowPlaying | null> {
    const player = this.players[intent.player]
    await this.ensureLoaded(player, intent)
    if (decision.shouldPlay !== this.appliedDecision) {
      await (decision.shouldPlay ? player.play() : player.pause())
      this.appliedDecision = decision.shouldPlay
    }
    const playing = await player.nowPlaying()
    if (playing === null) this.loadedKey = null

    return playing
  }

  private async ensureLoaded(player: MusicPlayer, intent: PlayerIntent): Promise<void> {
    const key = `${intent.player}:${intent.playlistId}`
    if (this.loadedKey === key) return
    await player.load(intent.playlistId)
    this.loadedKey = key
    this.appliedDecision = null
  }

  private async report(error: unknown): Promise<void> {
    const notice = error instanceof PlayerError ? error.message : `Coding Tunes: ${String(error)}`
    if (notice !== this.lastNotice) this.notifier.notify(notice)
    this.lastNotice = notice
    this.loadedKey = null
    this.retryLoadAt = (await this.clock.now().catch(() => 0)) + LOAD_RETRY_MS
    const intent = await this.board.readIntent().catch(() => undefined)
    await this.showSnapshot(intent, { shouldPlay: false, holder: null }, null, notice).catch(() => undefined)
  }

  private async showSnapshot(
    intent: PlayerIntent | undefined,
    decision: PlaybackDecision,
    playing: NowPlaying | null,
    notice: string | null,
  ): Promise<void> {
    if (notice === null) this.lastNotice = null
    this.frame += 1
    const holder = decision.holder
    await this.sink.show({
      player: intent?.isEnabled === true ? intent.player : null,
      playlistId: intent?.isEnabled === true ? intent.playlistId : null,
      track: playing?.track ?? '',
      isPlaying: playing?.isPlaying ?? false,
      elapsedSeconds: playing?.elapsedSeconds ?? null,
      heldBy: holder?.label ?? null,
      isHeldHere: holder?.sessionId === this.identity.sessionId,
      notice,
      frame: this.frame,
    })
  }
}
