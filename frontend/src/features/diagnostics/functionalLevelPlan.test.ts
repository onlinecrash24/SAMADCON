import { describe, expect, it } from 'vitest'

import type { FunctionalLevelState } from '../../api/types'
import { confirmMatches, raisePayload, scopesFor } from './functionalLevelPlan'

// zmb-ad as measured: domain and forest at 2008 R2.
const state = (domain_level: number, forest_level: number): FunctionalLevelState => ({
  is_samba: true,
  domain_level,
  domain_level_name: '',
  forest_level,
  forest_level_name: '',
  mixed: false,
  controllers: [],
  forest_revision: 5,
  domain_revision: 5,
  schema_version: 69,
  targets: [],
})

describe('what a raise may cover', () => {
  it('offers domain and forest together, or the domain alone, while the domain is below', () => {
    expect(scopesFor(state(4, 4), 7)).toEqual(['both', 'domain'])
  })

  it('offers only the forest once the domain is there', () => {
    // samba-tool refuses a forest above the domain, so "forest alone" only
    // exists when the domain has already been raised.
    expect(scopesFor(state(7, 4), 7)).toEqual(['forest'])
  })
})

describe('what is sent', () => {
  it('sends both levels for both', () => {
    expect(raisePayload(state(4, 4), 7, 'both')).toEqual({ domain_level: 7, forest_level: 7 })
  })

  it('sends the domain alone', () => {
    expect(raisePayload(state(4, 4), 6, 'domain')).toEqual({ domain_level: 6, forest_level: null })
  })

  it('sends the forest alone', () => {
    expect(raisePayload(state(7, 4), 7, 'forest')).toEqual({ domain_level: null, forest_level: 7 })
  })

  it('sends nothing for a choice that does not fit', () => {
    expect(raisePayload(state(7, 4), 7, 'domain')).toBeNull()
    expect(raisePayload(state(4, 4), 7, 'forest')).toBeNull()
    expect(raisePayload(state(7, 7), 7, 'both')).toBeNull()
  })
})

describe('the confirmation', () => {
  it('is the domain name, in any case, with stray spaces', () => {
    expect(confirmMatches(' MyAntiSpam.Local ', 'myantispam.local')).toBe(true)
  })

  it('is nothing else', () => {
    expect(confirmMatches('', 'myantispam.local')).toBe(false)
    expect(confirmMatches('myantispam', 'myantispam.local')).toBe(false)
  })
})
