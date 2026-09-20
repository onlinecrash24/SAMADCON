import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  DEFAULT_LIST_SORT,
  isSortColumn,
  readListSort,
  toggleSort,
  writeListSort,
} from './listSort'

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

describe('toggling a column', () => {
  it('sorts a new column ascending', () => {
    expect(toggleSort({ column: 'name', descending: true }, 'description')).toEqual({
      column: 'description',
      descending: false,
    })
  })

  it('flips the direction of the same column', () => {
    const once = toggleSort(DEFAULT_LIST_SORT, 'name')
    expect(once).toEqual({ column: 'name', descending: true })
    expect(toggleSort(once, 'name')).toEqual({ column: 'name', descending: false })
  })
})

describe('the remembered sort', () => {
  let storage: Storage

  beforeEach(() => {
    storage = fakeStorage()
    Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true })
  })
  afterEach(() => {
    // @ts-expect-error — removing what the test installed
    delete globalThis.localStorage
  })

  it('is by name ascending until chosen', () => {
    expect(readListSort()).toEqual(DEFAULT_LIST_SORT)
  })

  it('round-trips', () => {
    writeListSort({ column: 'description', descending: true })
    expect(readListSort()).toEqual({ column: 'description', descending: true })
  })

  it('refuses anything hand-edited into a shape the server would reject', () => {
    for (const bad of [
      '{"column":"sAMAccountName","descending":false}',
      '{"column":"name","descending":"yes"}',
      '{"column":"name"}',
      '"name"',
      'null',
      'not json',
    ]) {
      storage.setItem('samadcon.listSort', bad)
      expect(readListSort(), bad).toEqual(DEFAULT_LIST_SORT)
    }
  })

  it('drops extra fields rather than passing them on', () => {
    storage.setItem('samadcon.listSort', '{"column":"type","descending":false,"limit":99}')
    expect(readListSort()).toEqual({ column: 'type', descending: false })
  })

  it('knows its columns', () => {
    expect(isSortColumn('type')).toBe(true)
    expect(isSortColumn('cn')).toBe(false)
    expect(isSortColumn(1)).toBe(false)
  })
})
