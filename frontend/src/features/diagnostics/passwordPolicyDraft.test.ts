import { describe, expect, it } from 'vitest'

import type { PasswordPolicy } from '../../api/types'
import { changesBetween, draftFrom } from './passwordPolicyDraft'

// The tester's domain, as SAMADCON read it.
const POLICY: PasswordPolicy = {
  min_length: 7,
  history_length: 24,
  min_age_days: 1,
  max_age_days: 42,
  complexity: true,
  reversible_encryption: false,
  lockout_threshold: 0,
  lockout_duration_minutes: 30,
  lockout_window_minutes: 30,
  password_settings_objects: [],
}

describe('the password policy form', () => {
  it('starts from what the domain holds', () => {
    expect(draftFrom(POLICY)).toEqual({
      complexity: true,
      reversible_encryption: false,
      min_length: '7',
      history_length: '24',
      min_age_days: '1',
      max_age_days: '42',
      lockout_threshold: '0',
      lockout_duration_minutes: '30',
      lockout_window_minutes: '30',
    })
  })

  it('shows "never" and "none" as 0, which is how they are written back', () => {
    const draft = draftFrom({
      ...POLICY,
      max_age_days: null,
      min_age_days: null,
      lockout_duration_minutes: null,
    })
    expect([draft.max_age_days, draft.min_age_days, draft.lockout_duration_minutes]).toEqual([
      '0',
      '0',
      '0',
    ])
  })

  it('sends only what was changed', () => {
    const draft = { ...draftFrom(POLICY), complexity: false, min_length: '6' }
    expect(changesBetween(POLICY, draft)).toEqual({ complexity: false, min_length: 6 })
  })

  it('sends nothing when nothing was changed, fractional days included', () => {
    const odd = { ...POLICY, max_age_days: 42.5 }
    expect(changesBetween(odd, draftFrom(odd))).toEqual({})
  })

  it('refuses a field that is not a whole number', () => {
    expect(changesBetween(POLICY, { ...draftFrom(POLICY), min_length: '6.5' })).toBeNull()
    expect(changesBetween(POLICY, { ...draftFrom(POLICY), min_length: '' })).toBeNull()
    expect(changesBetween(POLICY, { ...draftFrom(POLICY), min_length: 'sechs' })).toBeNull()
  })

  it('leaves the range to the server, which says which one in words', () => {
    expect(changesBetween(POLICY, { ...draftFrom(POLICY), min_length: '15' })).toEqual({
      min_length: 15,
    })
  })
})
