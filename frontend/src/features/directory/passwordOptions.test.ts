import { describe, expect, it } from 'vitest'

import { bothSet, choosePasswordOption } from './passwordOptions'

// ADUC clears one when the other is ticked. SAMADCON let a tester save both.

describe('must change and never expires', () => {
  it('ticking "must change" clears "never expires", and says so', () => {
    expect(choosePasswordOption({ mustChange: false, neverExpires: true }, 'mustChange', true)).toEqual({
      next: { mustChange: true, neverExpires: false },
      cleared: 'neverExpires',
    })
  })

  it('ticking "never expires" clears "must change", and says so', () => {
    expect(choosePasswordOption({ mustChange: true, neverExpires: false }, 'neverExpires', true)).toEqual({
      next: { mustChange: false, neverExpires: true },
      cleared: 'mustChange',
    })
  })

  it('clears nothing when the other was not ticked', () => {
    expect(choosePasswordOption({ mustChange: false, neverExpires: false }, 'mustChange', true)).toEqual({
      next: { mustChange: true, neverExpires: false },
      cleared: null,
    })
  })

  it('unticking touches only the one unticked', () => {
    expect(choosePasswordOption({ mustChange: true, neverExpires: true }, 'neverExpires', false)).toEqual({
      next: { mustChange: true, neverExpires: false },
      cleared: null,
    })
  })

  it('notices an account that already has both', () => {
    expect(bothSet({ mustChange: true, neverExpires: true })).toBe(true)
    expect(bothSet({ mustChange: true, neverExpires: false })).toBe(false)
  })
})
