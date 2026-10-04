import { describe, expect, it } from 'vitest'

import type { AttributeEntry } from '../../api/types'
import { attributeRows, cannotSave, valuesFromText } from './attributeRows'

const set = (text: string, extra: Partial<AttributeEntry> = {}): AttributeEntry => ({
  values: [{ text }],
  editable: true,
  ...extra,
})
const empty = (extra: Partial<AttributeEntry> = {}): AttributeEntry => ({
  values: [],
  editable: true,
  empty: true,
  ...extra,
})

describe('the attribute rows', () => {
  it('lists attributes with a value before empty ones, each by name', () => {
    const rows = attributeRows(
      { info: empty(), sn: set('Muster'), cn: set('Max'), department: empty() },
      '',
    )
    expect(rows.map(([name]) => name)).toEqual(['cn', 'sn', 'department', 'info'])
  })

  it('filters by name without regard to case, empty ones included', () => {
    const rows = attributeRows({ otherMobile: empty(), mobile: set('1'), cn: set('Max') }, 'MOB')
    expect(rows.map(([name]) => name)).toEqual(['mobile', 'otherMobile'])
  })
})

describe('saving an attribute', () => {
  it('turns non-empty lines into values', () => {
    expect(valuesFromText(' a \n\n b\n')).toEqual(['a', 'b'])
  })

  it('refuses two values for a single-valued attribute', () => {
    expect(cannotSave(empty({ single_valued: true }), ['a', 'b'])).toBe('single_valued')
    expect(cannotSave(empty({ single_valued: true }), ['a'])).toBeNull()
  })

  it('lets several values through where the schema allows or does not say', () => {
    expect(cannotSave(empty({ single_valued: false }), ['a', 'b'])).toBeNull()
    expect(cannotSave(set('x'), ['a', 'b'])).toBeNull()
  })

  it('does not send a delete for an attribute that has nothing', () => {
    expect(cannotSave(empty(), [])).toBe('nothing')
  })

  it('still lets an attribute with a value be cleared', () => {
    expect(cannotSave(set('x'), [])).toBeNull()
  })
})
