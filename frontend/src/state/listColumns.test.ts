import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  COLUMN_CATALOGUE,
  DEFAULT_COLUMNS,
  normaliseColumns,
  readListColumns,
  requestedColumns,
  writeListColumns,
} from './listColumns'

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

describe('the column list', () => {
  it('always starts with name, whatever was stored', () => {
    expect(normaliseColumns(['description', 'name', 'type'])).toEqual(['name', 'description', 'type'])
    expect(normaliseColumns(['department'])).toEqual(['name', 'department'])
    expect(normaliseColumns([])).toEqual(['name'])
  })

  it('drops what the catalogue does not know and what repeats', () => {
    expect(normaliseColumns(['name', 'password', 'mail', 'mail', 42, null])).toEqual(['name', 'mail'])
  })

  it('asks the server only for what a row does not carry anyway', () => {
    expect(requestedColumns(['name', 'type', 'description', 'department', 'mail'])).toEqual([
      'department',
      'mail',
    ])
    expect(requestedColumns(DEFAULT_COLUMNS)).toEqual([])
  })

  it('has no duplicate ids in the catalogue', () => {
    const ids = COLUMN_CATALOGUE.map((c) => c.id)
    expect(new Set(ids).size).toBe(ids.length)
  })
})

describe('the remembered columns', () => {
  let storage: Storage

  beforeEach(() => {
    storage = fakeStorage()
    Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true })
  })
  afterEach(() => {
    // @ts-expect-error — removing what the test installed
    delete globalThis.localStorage
  })

  it('are the default until chosen', () => {
    expect(readListColumns()).toEqual(DEFAULT_COLUMNS)
  })

  it('round-trip, normalised on the way in and out', () => {
    writeListColumns(['department', 'name', 'mail'])
    expect(readListColumns()).toEqual(['name', 'department', 'mail'])
  })

  it('shrink rather than break after an upgrade removes a column', () => {
    storage.setItem('samadcon.listColumns', '["name","gone_in_this_version","mail"]')
    expect(readListColumns()).toEqual(['name', 'mail'])
  })

  it('fall back on anything that is not a list', () => {
    for (const bad of ['"name"', '{"a":1}', 'null', 'not json']) {
      storage.setItem('samadcon.listColumns', bad)
      expect(readListColumns(), bad).toEqual(DEFAULT_COLUMNS)
    }
  })
})
