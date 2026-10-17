import { describe, expect, it } from 'vitest'

import type { PreferenceItem } from '../../../api/types'
import {
  type Draft,
  itemSummary,
  moved,
  toDraft,
  toPayload,
  withItem,
  without,
} from './preferenceList'
import { NO_OPTIONS } from './preferenceOptions'

const draft = (name: string, extra: Partial<Draft> = {}): Draft => ({
  kind: 'drive',
  uid: `{${name}}`,
  action: 'U',
  properties: { letter: name, path: `\\\\srv\\${name}` },
  values: [],
  members: [],
  options: NO_OPTIONS,
  targeting: [],
  name: `${name}:`,
  filter_names: [],
  has_password: false,
  ...extra,
})

const names = (list: Draft[]) => list.map((item) => item.name)

describe('the list of items', () => {
  const list = [draft('P'), draft('Q'), draft('R')]

  it('replaces an edited item where it stands', () => {
    const edited = draft('Q', { action: 'R' })
    const next = withItem(list, 1, edited)
    expect(names(next)).toEqual(['P:', 'Q:', 'R:'])
    expect(next[1]?.action).toBe('R')
  })

  it('appends a new one at the end, as GPMC does', () => {
    expect(names(withItem(list, null, draft('S')))).toEqual(['P:', 'Q:', 'R:', 'S:'])
  })

  it('moves an item up and down, and not past either end', () => {
    expect(names(moved(list, 2, -1))).toEqual(['P:', 'R:', 'Q:'])
    expect(names(moved(list, 0, 1))).toEqual(['Q:', 'P:', 'R:'])
    expect(moved(list, 0, -1)).toBe(list)
    expect(moved(list, 2, 1)).toBe(list)
  })

  it('removes one', () => {
    expect(names(without(list, 1))).toEqual(['P:', 'R:'])
  })

  it('does not change the list it was given', () => {
    moved(list, 2, -1)
    without(list, 0)
    withItem(list, 0, draft('X'))
    expect(names(list)).toEqual(['P:', 'Q:', 'R:'])
  })
})

describe('what is sent to the server', () => {
  it('carries targeting only where it is editable', () => {
    const [editable, readOnly] = toPayload([
      draft('P', { targeting: [{ type: 'computer', bool: 'AND', not: false, name: 'A' }] }),
      draft('Q', { targeting: null }),
    ])
    expect(editable?.targeting).toEqual({
      conditions: [{ type: 'computer', bool: 'AND', not: false, name: 'A' }],
    })
    expect(readOnly).not.toHaveProperty('targeting')
  })

  it('never sends what is only for display', () => {
    const [item] = toPayload([draft('P')])
    expect(Object.keys(item ?? {}).sort()).toEqual(
      ['action', 'kind', 'members', 'options', 'properties', 'targeting', 'uid', 'values'].sort(),
    )
  })
})

describe('reading an item into the form', () => {
  it('leaves targeting it cannot edit as null', () => {
    const item = {
      kind: 'drive',
      uid: '{1}',
      name: 'K:',
      status: 'K:',
      image: 0,
      changed: '',
      action: 'U',
      properties: {},
      values: [],
      members: [],
      bypass_errors: false,
      user_context: false,
      options: NO_OPTIONS,
      targeting: { editable: false, conditions: [] },
      has_password: false,
      filter_names: ['FilterCollection'],
    } satisfies PreferenceItem
    expect(toDraft(item).targeting).toBeNull()
  })
})

describe('the summary column', () => {
  it('shows what GPMC shows beside the name', () => {
    expect(itemSummary('drive', { path: '\\\\zmb-ad\\netlogon' })).toBe('\\\\zmb-ad\\netlogon')
    expect(
      itemSummary('registry', {
        hive: 'HKEY_LOCAL_MACHINE',
        key: 'SOFTWARE\\SAMADCON-Test',
        name: 'Probe',
      }),
    ).toBe('HKEY_LOCAL_MACHINE\\SOFTWARE\\SAMADCON-Test › Probe')
    expect(itemSummary('registry', { hive: 'HKEY_CURRENT_USER', key: '\\Software\\X', name: '' })).toBe(
      'HKEY_CURRENT_USER\\Software\\X',
    )
    expect(itemSummary('port', { ipAddress: '10.0.0.5', path: '' })).toBe('10.0.0.5')
    expect(itemSummary('immediate_v2', { runAs: 'NT AUTHORITY\\System' })).toBe(
      'NT AUTHORITY\\System',
    )
  })

  it('is empty for a kind it has nothing to say about', () => {
    expect(itemSummary('unknown', { anything: 'x' })).toBe('')
  })
})
