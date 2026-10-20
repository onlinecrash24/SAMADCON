import { describe, expect, it } from 'vitest'

import { carriedFields, missingRequired } from './requiredUserFields'

// A tester registers users for Authelia, which needs a mail address on every
// account. The fields SAMADCON's settings make mandatory are checked in the
// New user and Copy dialogs before "Create" is offered; the server checks
// them again.

describe('which required fields are still empty', () => {
  it('lists each one that has no value', () => {
    expect(missingRequired(['mail', 'department'], { first_name: 'Anna' })).toEqual([
      'mail',
      'department',
    ])
  })

  it('counts spaces as empty', () => {
    expect(missingRequired(['mail'], { mail: '   ' })).toEqual(['mail'])
  })

  it('is nothing once every one is filled', () => {
    expect(missingRequired(['mail'], { mail: 'anna@example.test' })).toEqual([])
    expect(missingRequired([], {})).toEqual([])
  })

  it('counts what a copy takes from its template as filled', () => {
    expect(missingRequired(['mail', 'department'], {}, ['department'])).toEqual(['mail'])
  })
})

describe('what a copy takes from its template', () => {
  it('is what the server copies and the template has a value for', () => {
    expect(
      carriedFields(['department', 'company', 'city'], { department: 'Vertrieb', company: '', mail: 'x@y.z' }),
    ).toEqual(['department'])
  })
})
