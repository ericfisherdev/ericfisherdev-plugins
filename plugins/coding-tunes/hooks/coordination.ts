import type { PlayerKind } from '../types'
import type { SharedFiles } from './ports'

/** Why a session needs the person's input. */
export type HoldReason = 'permission' | 'question'

/** What one session publishes about itself to every other session. */
export type SessionRecord = {
  sessionId: string
  label: string
  heartbeatAt: number
  /** When its current turn began; null while idle. */
  workingSince: number | null
  holdReason: HoldReason | null
  hasEnded: boolean
}

/** User override on top of the automatic play/pause rule. */
export type PlaybackOverride = 'none' | 'paused' | 'playing'

/** The one player every session shares: what to play. Only start and stop write it. */
export type PlayerIntent = {
  isEnabled: boolean
  player: PlayerKind
  playlistId: string
}

export type PlaybackDecision = {
  shouldPlay: boolean
  /** The live session whose pending input keeps the player paused. */
  holder: SessionRecord | null
}

export const WORK_THRESHOLD_MS = 10_000
export const STALE_AFTER_MS = 15_000
const PRUNE_AFTER_MS = 60 * 60 * 1000

/** Sessions that ended or stopped sending heartbeats are no longer counted. */
export const liveRecords = (records: readonly SessionRecord[], now: number): SessionRecord[] =>
  records.filter(record => !record.hasEnded && now - record.heartbeatAt <= STALE_AFTER_MS)

/**
 * The shared play/pause rule. Any live session awaiting input holds the player
 * paused, whatever anyone else wants. Otherwise the person's override wins,
 * and with none the player plays while some session has worked 10 s or more.
 */
export const decidePlayback = (
  intent: PlayerIntent | undefined,
  override: PlaybackOverride,
  records: readonly SessionRecord[],
  now: number,
): PlaybackDecision => {
  const live = liveRecords(records, now)
  const holder = live.find(record => record.holdReason !== null) ?? null
  if (intent === undefined || !intent.isEnabled || holder !== null) return { shouldPlay: false, holder }
  if (override !== 'none') return { shouldPlay: override === 'playing', holder }
  const isAnyoneWorking = live.some(
    record => record.workingSince !== null && now - record.workingSince >= WORK_THRESHOLD_MS,
  )

  return { shouldPlay: isAnyoneWorking, holder }
}

/**
 * Per-session files under one runtime folder. Each session writes only its own
 * record, so no lock is needed. The intent is written whole only by start and
 * stop, and the override sits in a file of its own, so the turn hooks that
 * clear an override can never put back an intent another session replaced.
 */
export class SharedBoard {
  constructor(
    private readonly files: SharedFiles,
    private readonly root: string,
  ) {}

  get folder(): string {
    return this.root
  }

  async publish(record: SessionRecord): Promise<void> {
    await this.files.write(this.recordPath(record.sessionId), JSON.stringify(record))
  }

  async records(): Promise<SessionRecord[]> {
    const names = await this.files.list(this.sessionsDir())
    const texts = await Promise.all(names.map(name => this.files.read(`${this.sessionsDir()}/${name}`)))

    return texts.flatMap(text => parseJson<SessionRecord>(text) ?? [])
  }

  async readIntent(): Promise<PlayerIntent | undefined> {
    return parseJson<PlayerIntent>(await this.files.read(this.intentPath()))
  }

  async writeIntent(intent: PlayerIntent): Promise<void> {
    await this.files.write(this.intentPath(), JSON.stringify(intent))
  }

  /** The person's play/pause override; a file of its own so writing it never rewrites the intent. */
  async readOverride(): Promise<PlaybackOverride> {
    return parseJson<PlaybackOverride>(await this.files.read(this.overridePath())) ?? 'none'
  }

  async writeOverride(override: PlaybackOverride): Promise<void> {
    await this.files.write(this.overridePath(), JSON.stringify(override))
  }

  /** Removes records of sessions dead for an hour, so the folder stays small. */
  async prune(records: readonly SessionRecord[], now: number): Promise<void> {
    const dead = records.filter(record => record.hasEnded || now - record.heartbeatAt > PRUNE_AFTER_MS)
    await Promise.all(dead.map(record => this.files.remove(this.recordPath(record.sessionId))))
  }

  private sessionsDir(): string {
    return `${this.root}/sessions`
  }

  private recordPath(sessionId: string): string {
    return `${this.sessionsDir()}/${sessionId.replace(/[^A-Za-z0-9_-]/g, '_')}.json`
  }

  private intentPath(): string {
    return `${this.root}/intent.json`
  }

  private overridePath(): string {
    return `${this.root}/override.json`
  }
}

/** A half-written file from a concurrent writer reads as missing this tick. */
const parseJson = <T>(text: string | undefined): T | undefined => {
  if (text === undefined) return undefined
  try {
    return JSON.parse(text) as T
  } catch {
    return undefined
  }
}
