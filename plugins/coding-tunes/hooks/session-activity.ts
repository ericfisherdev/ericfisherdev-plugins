import type { HoldReason, SessionRecord } from './coordination'

/**
 * What this session is doing, as the play/pause rule needs it: whether a turn
 * runs, and whether a question or a permission prompt waits on the person.
 */
export class SessionActivity {
  private workingSince: number | null = null
  private readonly openQuestions = new Set<string>()
  private readonly askedToolCalls = new Set<string>()
  private isPermissionPromptOpen = false
  private isHoldWaived = false

  beginTurn(now: number): void {
    this.workingSince = now
  }

  /** A finished turn answers every prompt it raised. */
  endTurn(): void {
    this.workingSince = null
    this.openQuestions.clear()
    this.askedToolCalls.clear()
    this.isPermissionPromptOpen = false
    this.isHoldWaived = false
  }

  openQuestion(toolUseId: string): void {
    this.openQuestions.add(toolUseId)
    this.isHoldWaived = false
  }

  closeQuestion(toolUseId: string): void {
    this.openQuestions.delete(toolUseId)
  }

  /** The engine's verdict for this call was `ask`: a prompt may follow. */
  markAsked(toolUseId: string): void {
    this.askedToolCalls.add(toolUseId)
  }

  openPermissionPrompt(): void {
    this.isPermissionPromptOpen = true
    this.isHoldWaived = false
  }

  /** A call settled; once no asked call is pending, no permission prompt is open. */
  settleToolCall(toolUseId: string): void {
    if (!this.askedToolCalls.delete(toolUseId)) return
    if (this.askedToolCalls.size === 0) this.isPermissionPromptOpen = false
  }

  /** The person pressed play here while this session holds: let it play anyway. */
  waiveHold(): void {
    this.isHoldWaived = true
  }

  /** Whether a turn of this session is running. */
  isWorking(): boolean {
    return this.workingSince !== null
  }

  holdReason(): HoldReason | null {
    if (this.isHoldWaived) return null
    if (this.openQuestions.size > 0) return 'question'

    return this.isPermissionPromptOpen ? 'permission' : null
  }

  toRecord(sessionId: string, label: string, now: number): SessionRecord {
    return {
      sessionId,
      label,
      heartbeatAt: now,
      workingSince: this.workingSince,
      holdReason: this.holdReason(),
      hasEnded: false,
    }
  }
}
