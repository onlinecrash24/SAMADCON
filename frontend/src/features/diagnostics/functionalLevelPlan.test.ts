import { describe, expect, it } from 'vitest'

import type { FunctionalLevelTarget } from '../../api/types'
import { chosenRaise } from './functionalLevelPlan'

const target = (raise: FunctionalLevelTarget['raise']): FunctionalLevelTarget => ({
  level: 7,
  name: 'Windows Server 2016',
  domain: true,
  missing: [],
  raise,
})

const BOTH = {
  scope: 'both' as const,
  command: 'samba-tool domain level raise --domain-level=2016 --forest-level=2016',
}
const DOMAIN = { scope: 'domain' as const, command: 'samba-tool domain level raise --domain-level=2016' }

describe('the command shown for the DC', () => {
  it('is the one for the chosen scope', () => {
    expect(chosenRaise(target([BOTH, DOMAIN]), 'domain')).toBe(DOMAIN)
  })

  it('falls back to the first the server offers when the choice does not fit', () => {
    // After switching to a level where only the forest can move, a "both"
    // left over from before must not show a command for something else.
    expect(chosenRaise(target([BOTH, DOMAIN]), 'forest')).toBe(BOTH)
  })

  it('is none on a Windows DC, where samba-tool has nothing to say', () => {
    expect(chosenRaise(target([]), 'both')).toBeNull()
  })
})
