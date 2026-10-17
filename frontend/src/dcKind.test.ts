import { describe, expect, it } from 'vitest'

import { isSambaDc } from './dcKind'

describe('isSambaDc', () => {
  it('is true for the vendorName Samba sends', () => {
    // Measured on Samba 4.22.11.
    expect(isSambaDc({ dc_vendor: 'Samba Team (https://www.samba.org)' })).toBe(true)
  })

  it('is false for a Windows DC, which sends no vendorName', () => {
    expect(isSambaDc({ dc_vendor: null })).toBe(false)
    expect(isSambaDc({})).toBe(false)
  })

  it('is false without a session or for another server', () => {
    expect(isSambaDc(null)).toBe(false)
    expect(isSambaDc(undefined)).toBe(false)
    expect(isSambaDc({ dc_vendor: 'Some LDAP server' })).toBe(false)
  })
})
