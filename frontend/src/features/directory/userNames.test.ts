import { describe, expect, it } from 'vitest'

import { defaultCommonName } from './userNames'

// One tester wanted the logon name as a new user's CN, a later one first and
// last name, as ADUC builds it. SAMADCON's settings choose; ADUC's rule is
// the default.

describe('what the CN of a new user starts as, from the name', () => {
  it('is first and last name, as in ADUC', () => {
    expect(defaultCommonName('Max', 'Muster', 'mmuster', 'name')).toBe('Max Muster')
  })

  it('is whichever of the two is given', () => {
    expect(defaultCommonName('', 'Muster', 'mmuster', 'name')).toBe('Muster')
    expect(defaultCommonName('Max', '  ', 'mmuster', 'name')).toBe('Max')
  })

  it('is the logon name when neither is given', () => {
    expect(defaultCommonName('', '', 'mmuster', 'name')).toBe('mmuster')
  })

  it('fits a CN, which takes 64 characters', () => {
    expect(defaultCommonName('A'.repeat(40), 'B'.repeat(40), 'x', 'name')).toHaveLength(64)
  })
})

describe('what the CN of a new user starts as, from the logon name', () => {
  it('is the logon name, whatever the names say', () => {
    expect(defaultCommonName('Max', 'Muster', 'mmuster', 'logon')).toBe('mmuster')
  })
})
