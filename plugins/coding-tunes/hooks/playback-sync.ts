import { decidePlayback, liveRecords } from './coordination'
import type { PlaybackDecision, PlayerIntent, SharedBoard } from './coordination'
import { PlayerError } from './players/music-player'
import type { MusicPlayer, NowPlaying, PlayerRegistry } from './players/music-player'
import type { Clock, Notifier, SnapshotSink } from './ports'
import type { SessionActivity } from './session-activity'

export type SessionIdentity = { sessionId: string; label: string }

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

  /** Runs one sync after any already queued; never rejects. */
  reconcile(): Promise<void> {
    this.queue = this.queue.then(() => this.syncOnce()).catch(error => this.report(error))

    return this.queue
  }

  /** Forgets what was loaded and applied, so the next sync loads and decides afresh. */
  forceReload(): void {
    this.loadedKey = null
    this.appliedDecision = null
  }

  /** The current decision, for user controls that must respect holds. */
  async currentDecision(): Promise<PlaybackDecision> {
    const now = await this.clock.now()

    return decidePlayback(await this.board.readIntent(), await this.board.records(), now)
  }

  /** Marks this session ended; the last live session shuts the player down. */
  async end(): Promise<void> {
    const now = await this.clock.now()
    await this.board.publish({ ...this.activity.toRecord(this.identity.sessionId, this.identity.label, now), hasEnded: true })
    const others = liveRecords(await this.board.records(), now)
    const intent = await this.board.readIntent()
    if (others.length === 0 && intent?.isEnabled === true) await this.players[intent.player].shutdown()
  }

  private async syncOnce(): Promise<void> {
    const now = await this.clock.now()
    await this.board.publish(this.activity.toRecord(this.identity.sessionId, this.identity.label, now))
    const records = await this.board.records()
    const intent = await this.board.readIntent()
    const decision = decidePlayback(intent, records, now)
    const playing = intent?.isEnabled === true ? await this.drive(intent, decision) : null
    await this.board.prune(records, now)
    await this.showSnapshot(intent, decision, playing, null)
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
