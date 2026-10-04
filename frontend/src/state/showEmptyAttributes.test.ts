import { beforeEach, describe, expect, it } from 'vitest'

import { readShowEmptyAttributes, writeShowEmptyAttributes } from './showEmptyAttributes'

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

describe('showing empty attributes', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'localStorage', {
      value: fakeStorage(),
      configurable: true,
    })
  })

  it('is off until switched on', () => {
    expect(readShowEmptyAttributes()).toBe(false)
  })

  it('is remembered', () => {
    writeShowEmptyAttributes(true)
    expect(readShowEmptyAttributes()).toBe(true)
    writeShowEmptyAttributes(false)
    expect(readShowEmptyAttributes()).toBe(false)
  })

  it('reads anything but true as off', () => {
    localStorage.setItem('samadcon.showEmptyAttributes', 'yes')
    expect(readShowEmptyAttributes()).toBe(false)
  })

  it('is off when storage cannot be read', () => {
    Object.defineProperty(globalThis, 'localStorage', {
      get() {
        throw new Error('blocked')
      },
      configurable: true,
    })
    expect(readShowEmptyAttributes()).toBe(false)
  })
})
