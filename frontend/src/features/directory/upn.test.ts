import { describe, expect, it } from 'vitest'

import { composeUpn, splitUpn, upnOptions } from './upn'

describe('a user principal name', () => {
  it('splits at the last @', () => {
    expect(splitUpn('anna@example.test')).toEqual({ local: 'anna', suffix: 'example.test' })
    // Not well-formed, but read from a directory — the suffix is what follows
    // the last @, not the first.
    expect(splitUpn('a@b@example.test')).toEqual({ local: 'a@b', suffix: 'example.test' })
  })

  it('has no suffix when there is no @', () => {
    expect(splitUpn('anna')).toEqual({ local: 'anna', suffix: '' })
    expect(splitUpn('')).toEqual({ local: '', suffix: '' })
  })

  it('composes back to the same string', () => {
    for (const value of ['anna@example.test', 'a@b@c', 'x@']) {
      const { local, suffix } = splitUpn(value)
      expect(composeUpn(local, suffix)).toBe(value)
    }
  })

  it('is empty when the name is empty, whatever the suffix', () => {
    // The sheet turns an emptied field into "remove the attribute"; a bare
    // "@example.test" would instead be written as a UPN.
    expect(composeUpn('', 'example.test')).toBe('')
  })

  it('offers the forest and keeps an unknown suffix of the current value', () => {
    const forest = ['example.test', 'corp.example.com']
    expect(upnOptions(forest, 'example.test')).toEqual(forest)
    expect(upnOptions(forest, 'EXAMPLE.TEST')).toEqual(forest)
    expect(upnOptions(forest, 'old.example.org')).toEqual([...forest, 'old.example.org'])
    expect(upnOptions(forest, '')).toEqual(forest)
  })

  it('does not hand back the caller its own array', () => {
    const forest = ['example.test']
    const options = upnOptions(forest, 'example.test')
    options.push('x')
    expect(forest).toEqual(['example.test'])
  })
})
