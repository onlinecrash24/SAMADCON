/**
 * The domain's password policy as a form, and what saving it sends.
 *
 * Numbers are kept as the text typed, so a half-typed value is not turned
 * into something else under the cursor. Only fields that differ from the
 * domain are sent: the server leaves the rest as it is, and an unchanged
 * value can then never be rewritten by accident. The ranges are checked by
 * the server, which names the field in its message.
 */

import type { PasswordPolicy, PasswordPolicyChanges } from '../../api/types'

const NUMBERS = [
  'min_length',
  'history_length',
  'min_age_days',
  'max_age_days',
  'lockout_threshold',
  'lockout_duration_minutes',
  'lockout_window_minutes',
] as const

type NumberField = (typeof NUMBERS)[number]

export type PolicyDraft = { complexity: boolean; reversible_encryption: boolean } & Record<
  NumberField,
  string
>

/**
 * What the domain holds, as the form shows it. "Never" and "none" read back
 * as null and are written as 0, so the form shows 0 for them.
 */
export function draftFrom(policy: PasswordPolicy): PolicyDraft {
  const draft = {
    complexity: policy.complexity,
    reversible_encryption: policy.reversible_encryption,
  } as PolicyDraft
  for (const field of NUMBERS) draft[field] = String(Math.round(policy[field] ?? 0))
  return draft
}

/** The fields to send, or null while one of them is not a whole number. */
export function changesBetween(
  policy: PasswordPolicy,
  draft: PolicyDraft,
): PasswordPolicyChanges | null {
  const changes: PasswordPolicyChanges = {}
  if (draft.complexity !== policy.complexity) changes.complexity = draft.complexity
  if (draft.reversible_encryption !== policy.reversible_encryption) {
    changes.reversible_encryption = draft.reversible_encryption
  }
  const original = draftFrom(policy)
  for (const field of NUMBERS) {
    const text = draft[field].trim()
    if (!/^\d+$/.test(text)) return null
    if (text !== original[field]) changes[field] = Number(text)
  }
  return changes
}
