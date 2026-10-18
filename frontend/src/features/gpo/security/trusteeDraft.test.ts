import { describe, expect, it } from 'vitest'

import type { SecurityTrustee } from '../../../api/types'
import { trusteeValue, trusteesChanged, withTrustee, withoutTrustee } from './trusteeDraft'

// User rights and restricted groups wrote each added or removed account the
// moment it was picked, beside settings that wait for Save. Each card now
// holds a draft until Save, and Discard drops it.

const admins: SecurityTrustee = { sid: 'S-1-5-32-544', name: 'Administrators', kind: 'group' }
const users: SecurityTrustee = { sid: 'S-1-5-32-545', name: 'Users', kind: 'group' }
const anna: SecurityTrustee = { sid: 'S-1-5-21-1-2-3-1105', name: 'Anna', kind: 'user' }

describe('a card of accounts', () => {
  it('adds an account once', () => {
    const once = withTrustee([admins], anna)
    expect(once).toEqual([admins, anna])
    expect(withTrustee(once, { ...anna, name: 'anna' })).toEqual(once)
  })

  it('takes an account out by its SID', () => {
    expect(withoutTrustee([admins, anna], anna.sid)).toEqual([admins])
  })

  it('compares SIDs regardless of case', () => {
    expect(withoutTrustee([anna], anna.sid.toLowerCase())).toEqual([])
  })

  it('is unchanged when the same accounts are there, in any order', () => {
    expect(trusteesChanged([admins, users], [users, admins])).toBe(false)
    expect(trusteesChanged([admins], [admins, anna])).toBe(true)
    expect(trusteesChanged([admins, anna], [admins])).toBe(true)
  })

  it('is unchanged after an account is added and taken out again', () => {
    const back = withoutTrustee(withTrustee([admins], anna), anna.sid)
    expect(trusteesChanged([admins], back)).toBe(false)
  })

  it('saves the SIDs, and nothing at all once the last account is gone', () => {
    expect(trusteeValue([admins, anna])).toEqual([admins.sid, anna.sid])
    expect(trusteeValue([])).toBeNull()
  })
})
