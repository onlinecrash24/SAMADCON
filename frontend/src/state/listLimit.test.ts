import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  DEFAULT_LIST_LIMIT,
  LIST_LIMITS,
  isListLimit,
  readListLimit,
  writeListLimit,
} from './listLimit'

/** A localStorage that lives for one test. */
function fakeStorage() {
  const map = new Map<string, string>()
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => void map.set(key, value),
    removeItem: (key: string) => void map.delete(key),
    clear: () => map.clear(),
    key: () => null,
    length: 0,
  } as unknown as Storage
}

describe('the list limit', () => {
  let storage: Storage

  beforeEach(() => {
    storage = fakeStorage()
    Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true })
  })
  afterEach(() => {
    // @ts-expect-error — removing what the test installed
    delete globalThis.localStorage
  })

  it('is the default when nothing was ever chosen', () => {
    expect(readListLimit()).toBe(DEFAULT_LIST_LIMIT)
  })

  it('remembers a choice', () => {
    writeListLimit(5000)
    expect(readListLimit()).toBe(5000)
  })

  it('offers only what the server accepts', () => {
    // The API caps `limit` at 10 000; offering more would promise a 422.
    expect(Math.max(...LIST_LIMITS)).toBe(10000)
    expect(LIST_LIMITS).toContain(DEFAULT_LIST_LIMIT)
  })

  it('refuses a hand-edited value rather than obeying it', () => {
    for (const bad of ['999999', '"2000"', 'null', '{}', '-5', '0', 'not json']) {
      storage.setItem('samadcon.listLimit', bad)
      expect(readListLimit(), bad).toBe(DEFAULT_LIST_LIMIT)
    }
    // And one that is a number but not an offered one: same answer.
    storage.setItem('samadcon.listLimit', '1500')
    expect(readListLimit()).toBe(DEFAULT_LIST_LIMIT)
  })

  it('knows its own choices', () => {
    for (const limit of LIST_LIMITS) expect(isListLimit(limit)).toBe(true)
    expect(isListLimit(1500)).toBe(false)
    expect(isListLimit('2000')).toBe(false)
  })

  it('survives a storage that throws', () => {
    Object.defineProperty(globalThis, 'localStorage', {
      value: { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') } },
      configurable: true,
    })
    expect(readListLimit()).toBe(DEFAULT_LIST_LIMIT)
    expect(() => writeListLimit(500)).not.toThrow()
  })
})
