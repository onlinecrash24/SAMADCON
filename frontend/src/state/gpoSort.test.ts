import { beforeEach, describe, expect, it } from 'vitest'

import {
  DEFAULT_GPO_SORT,
  type GpoRow,
  readGpoSort,
  sortGpos,
  toggleGpoSort,
  writeGpoSort,
} from './gpoSort'

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

const row = (
  name: string | null,
  changed: string | null,
  order: number | null = null,
  guid = `{${name ?? 'X'}}`,
): GpoRow<{ display_name: string | null; guid: string; changed: string | null }> => ({
  gpo: { display_name: name, guid, changed },
  order,
})

const names = (rows: GpoRow<{ display_name: string | null; guid: string }>[]) =>
  rows.map(({ gpo }) => gpo.display_name ?? gpo.guid)

describe('sorting policies', () => {
  const rows = [
    row('zeta', '2026-01-03T10:00:00Z', 2),
    row('Alpha', '2026-03-01T10:00:00Z', 3),
    row('beta', '2025-12-24T10:00:00Z', 1),
  ]

  it('sorts by name without regard to case', () => {
    expect(names(sortGpos(rows, { column: 'name', descending: false }))).toEqual([
      'Alpha',
      'beta',
      'zeta',
    ])
  })

  it('reverses on request', () => {
    expect(names(sortGpos(rows, { column: 'name', descending: true }))).toEqual([
      'zeta',
      'beta',
      'Alpha',
    ])
  })

  it('sorts names with numbers as a person would', () => {
    const numbered = [row('GPO 10', null), row('GPO 2', null), row('GPO 1', null)]
    expect(names(sortGpos(numbered, { column: 'name', descending: false }))).toEqual([
      'GPO 1',
      'GPO 2',
      'GPO 10',
    ])
  })

  it('places a policy without a name by its GUID', () => {
    const mixed = [row('beta', null), row(null, null, null, '{0AAA}')]
    expect(names(sortGpos(mixed, { column: 'name', descending: false }))).toEqual([
      '{0AAA}',
      'beta',
    ])
  })

  it('sorts by the date it was changed, oldest first', () => {
    expect(names(sortGpos(rows, { column: 'changed', descending: false }))).toEqual([
      'beta',
      'zeta',
      'Alpha',
    ])
  })

  it('keeps policies without a date last, whichever way', () => {
    const undated = [row('a', null), row('b', '2026-01-01T00:00:00Z'), row('c', '2026-02-01T00:00:00Z')]
    expect(names(sortGpos(undated, { column: 'changed', descending: false }))).toEqual([
      'b',
      'c',
      'a',
    ])
    expect(names(sortGpos(undated, { column: 'changed', descending: true }))).toEqual([
      'c',
      'b',
      'a',
    ])
  })

  it('sorts by link order, 1 first', () => {
    expect(names(sortGpos(rows, { column: 'order', descending: false }))).toEqual([
      'beta',
      'zeta',
      'Alpha',
    ])
  })

  it('does not reorder the input', () => {
    const before = names(rows)
    sortGpos(rows, { column: 'name', descending: false })
    expect(names(rows)).toEqual(before)
  })
})

describe('the column header', () => {
  it('sorts a new column ascending and flips the same column', () => {
    const byName = toggleGpoSort({ column: 'order', descending: false }, 'name')
    expect(byName).toEqual({ column: 'name', descending: false })
    expect(toggleGpoSort(byName, 'name')).toEqual({ column: 'name', descending: true })
  })
})

describe('the remembered sort', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'localStorage', {
      value: fakeStorage(),
      configurable: true,
    })
  })

  it('starts by name for all policies and by link order for a container', () => {
    expect(readGpoSort('all')).toEqual({ column: 'name', descending: false })
    expect(readGpoSort('linked')).toEqual({ column: 'order', descending: false })
    expect(DEFAULT_GPO_SORT.linked.column).toBe('order')
  })

  it('remembers each view on its own', () => {
    writeGpoSort('all', { column: 'changed', descending: true })
    writeGpoSort('linked', { column: 'name', descending: false })
    expect(readGpoSort('all')).toEqual({ column: 'changed', descending: true })
    expect(readGpoSort('linked')).toEqual({ column: 'name', descending: false })
  })

  it('never sorts all policies by link order, which they do not have', () => {
    localStorage.setItem(
      'samadcon.gpoSort',
      JSON.stringify({ all: { column: 'order', descending: false } }),
    )
    expect(readGpoSort('all')).toEqual(DEFAULT_GPO_SORT.all)
  })

  it('falls back on anything it does not recognise', () => {
    localStorage.setItem('samadcon.gpoSort', '{"linked":{"column":"size","descending":1}}')
    expect(readGpoSort('linked')).toEqual(DEFAULT_GPO_SORT.linked)
    localStorage.setItem('samadcon.gpoSort', 'not json')
    expect(readGpoSort('all')).toEqual(DEFAULT_GPO_SORT.all)
  })
})
