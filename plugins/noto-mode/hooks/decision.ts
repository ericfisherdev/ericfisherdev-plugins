// The decision type the rules answer with, and its constructors. Pure.

export type Kind = 'allow' | 'ask' | 'classify'

export type Decision = {
  kind: Kind
  /** Why, in a short clause: `a read inside the working directories`. */
  reason: string
  /** What would make the same call pass next time; shown on a prompt. */
  fix?: string
}

export const NEVER_FIX =
  "noto-mode never approves this on its own (auto mode wouldn't either). Approve it here; to stop the prompt for good, add a permissions.allow rule in /permissions."
export const ADD_DIR_FIX =
  'add that directory with /add-dir (or permissions.additionalDirectories) so it counts as part of the project'
export const CLASSIFIER_FIX =
  'turn on the classifier (/config › noto-mode) to have a model judge calls like this, or add a permissions.allow rule for the command'

export const allow = (reason: string): Decision => ({ kind: 'allow', reason })
export const ask = (reason: string, fix: string = NEVER_FIX): Decision => ({ kind: 'ask', reason, fix })
export const classify = (reason: string, fix?: string): Decision => ({ kind: 'classify', reason, fix })

const RANK: Record<Kind, number> = { allow: 0, classify: 1, ask: 2 }
/** The stricter of two decisions. */
export const worse = (a: Decision, b: Decision): Decision => (RANK[b.kind] > RANK[a.kind] ? b : a)
