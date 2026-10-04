import { describe, expect, it } from 'vitest'

import { FIRST_TYPE, areaOf, typesIn } from './preferenceAreas'

// The server's catalogue, in its order (catalogue.py).
const CATALOGUE = [
  'drives',
  'registry',
  'files',
  'folders',
  'shortcuts',
  'environment',
  'printers',
  'groups',
  'services',
  'tasks',
].map((id) => ({ id }))

describe('the preference branches', () => {
  it('puts what GPMC files under Windows Settings there', () => {
    expect(typesIn('windows', CATALOGUE).map((type) => type.id)).toEqual([
      'drives',
      'registry',
      'files',
      'folders',
      'shortcuts',
      'environment',
    ])
  })

  it('puts what GPMC files under Control Panel Settings there', () => {
    expect(typesIn('controlPanel', CATALOGUE).map((type) => type.id)).toEqual([
      'printers',
      'groups',
      'services',
      'tasks',
    ])
  })

  it('loses no type between the two', () => {
    const shown = [...typesIn('windows', CATALOGUE), ...typesIn('controlPanel', CATALOGUE)]
    expect(shown).toHaveLength(CATALOGUE.length)
  })

  it('shows a type it does not know yet rather than hiding it', () => {
    expect(areaOf('ini')).toBe('windows')
  })

  it('opens each branch on one of its own types', () => {
    expect(areaOf(FIRST_TYPE.windows)).toBe('windows')
    expect(areaOf(FIRST_TYPE.controlPanel)).toBe('controlPanel')
  })
})
