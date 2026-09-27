import { describe, expect, it } from 'vitest'

import { auditChanges, shownValue } from './auditPolicy'

const LOGON = '{0cce9215-69ae-11d9-bed3-505054503030}'
const LOGOFF = '{0cce9216-69ae-11d9-bed3-505054503030}'
const LOCKOUT = '{0cce9217-69ae-11d9-bed3-505054503030}'

describe('what a category save sends', () => {
  const saved = { [LOGON]: 3, [LOGOFF]: 1 }

  it('sends only what the draft changed', () => {
    expect(auditChanges(saved, { [LOGON]: '3', [LOGOFF]: '2' }, [LOGON, LOGOFF, LOCKOUT])).toEqual({
      [LOGOFF]: 2,
    })
  })

  it('sends not configured as null and no auditing as 0 — they differ', () => {
    expect(auditChanges(saved, { [LOGON]: '', [LOGOFF]: '0' }, [LOGON, LOGOFF])).toEqual({
      [LOGON]: null,
      [LOGOFF]: 0,
    })
  })

  it('sends a newly configured subcategory', () => {
    expect(auditChanges(saved, { [LOCKOUT]: '2' }, [LOCKOUT])).toEqual({ [LOCKOUT]: 2 })
  })

  it('leaves out subcategories of other categories', () => {
    expect(auditChanges(saved, { [LOCKOUT]: '2' }, [LOGON])).toEqual({})
  })
})

describe('what the select shows', () => {
  it('is the draft, then the saved value, then not configured', () => {
    expect(shownValue({ [LOGON]: 3 }, { [LOGON]: '1' }, LOGON)).toBe('1')
    expect(shownValue({ [LOGON]: 3 }, {}, LOGON)).toBe('3')
    expect(shownValue({}, {}, LOGON)).toBe('')
  })
})
