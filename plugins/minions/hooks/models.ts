// The model tiers by alias, resolved to the ids a request names. A `turn.step`
// rewrite takes a full id, not an alias, so the dispatcher option is resolved
// here; a value that is no alias is taken as an id already.

export const MODEL_IDS = {
  haiku: 'claude-haiku-5-5',
  sonnet: 'claude-sonnet-5-5',
  opus: 'claude-opus-5-5',
  fable: 'claude-fable-5-1',
} as const

export type ModelAlias = keyof typeof MODEL_IDS

const isAlias = (value: string): value is ModelAlias => Object.hasOwn(MODEL_IDS, value)

/** The model id for an alias, or `value` itself when it is already an id. */
export const resolveModelId = (value: string): string => (isAlias(value) ? MODEL_IDS[value] : value)
