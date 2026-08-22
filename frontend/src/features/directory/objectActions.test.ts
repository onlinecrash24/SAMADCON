/**
 * What an object offers, and to whom.
 *
 * This is the list two screens share — the row of buttons in the detail pane
 * and the right-click menu — so it is the one place where a disagreement
 * would be invisible: nothing fails, one surface simply keeps offering the
 * old set. Hence a test rather than a click.
 */

import { describe, expect, it } from 'vitest'

import type { DirectoryObject } from '../../api/types'
import { contextMenuActions, detailRowActions, UNKNOWN } from './objectActions'

function object(overrides: Partial<DirectoryObject> = {}): DirectoryObject {
  return {
    dn: 'CN=Anna,OU=Benutzer,DC=example,DC=test',
    name: 'Anna',
    type: 'user',
    display_name: null,
    description: null,
    guid: null,
    is_container: false,
    advanced_only: false,
    when_created: null,
    when_changed: null,
    ...overrides,
  }
}

const ids = (entries: { kind: string; id?: string }[]) =>
  entries.filter((entry) => entry.kind === 'item').map((entry) => entry.id)

describe('what each type offers', () => {
  it('gives a user the account actions', () => {
    expect(ids(detailRowActions(object(), UNKNOWN))).toEqual([
      'disable',
      'unlock',
      'resetPassword',
      'rename',
      'move',
      'delete',
    ])
  })

  it('gives a managed service account the same, because it is one', () => {
    const msa = detailRowActions(object({ type: 'managed_service_account' }), UNKNOWN)
    expect(ids(msa)).toContain('resetPassword')
  })

  it('gives a computer its own reset and no password reset', () => {
    const actions = ids(detailRowActions(object({ type: 'computer' }), UNKNOWN))
    expect(actions).toContain('resetAccount')
    expect(actions).not.toContain('resetPassword')
    expect(actions).not.toContain('disable')
  })

  it('gives a group only what applies to any object', () => {
    expect(ids(detailRowActions(object({ type: 'group' }), UNKNOWN))).toEqual([
      'rename',
      'move',
      'delete',
    ])
  })

  it('offers move on everything, not only containers', () => {
    // Deliberate: move_object is generic, and a user in the wrong OU is the
    // commoner mistake.
    for (const type of ['user', 'group', 'computer', 'organizational_unit', 'contact']) {
      expect(ids(detailRowActions(object({ type: type as DirectoryObject['type'] }), UNKNOWN))).toContain(
        'move',
      )
    }
  })
})

describe('enable and disable need nothing loaded', () => {
  it('offers disabling an account that is running', () => {
    expect(ids(detailRowActions(object({ disabled: false }), UNKNOWN))).toContain('disable')
  })

  it('offers enabling one that is not', () => {
    expect(ids(detailRowActions(object({ disabled: true }), UNKNOWN))).toContain('enable')
  })

  it('prefers a loaded answer over the row, because it is fresher', () => {
    const stale = object({ disabled: true })
    const actions = ids(detailRowActions(stale, { disabled: false, lockedOut: false }))
    expect(actions).toContain('disable')
    expect(actions).not.toContain('enable')
  })

  it('treats a row with no flag at all as running', () => {
    expect(ids(detailRowActions(object(), UNKNOWN))).toContain('disable')
  })
})

describe('unlock is the one thing a row cannot know', () => {
  it('is offered when nothing is loaded, rather than silently missing', () => {
    // An absent "Entsperren" is indistinguishable from an account that is not
    // locked. Offering it and reporting the outcome is the honest half.
    expect(ids(contextMenuActions(object()))).toContain('unlock')
  })

  it('is offered when the account is known to be locked', () => {
    expect(ids(detailRowActions(object(), { disabled: null, lockedOut: true }))).toContain('unlock')
  })

  it('is left out only when the answer is known to be no', () => {
    expect(ids(detailRowActions(object(), { disabled: null, lockedOut: false }))).not.toContain(
      'unlock',
    )
  })

  it('is never offered for something that cannot be locked', () => {
    expect(ids(contextMenuActions(object({ type: 'group' })))).not.toContain('unlock')
  })
})

describe('the menu adds what a menu needs', () => {
  it('offers opening and creating inside a container', () => {
    const entries = contextMenuActions(object({ type: 'organizational_unit', is_container: true }))
    expect(ids(entries)).toContain('open')

    const submenu = entries.find((entry) => entry.kind === 'submenu')
    expect(submenu).toBeDefined()
    expect(submenu && 'items' in submenu && submenu.items.map((i) => i.id)).toEqual([
      'newUser',
      'newGroup',
      'newComputer',
      'newOu',
    ])
  })

  it('offers neither on something nothing can be created in', () => {
    const entries = contextMenuActions(object({ type: 'user' }))
    expect(ids(entries)).not.toContain('open')
    expect(entries.some((entry) => entry.kind === 'submenu')).toBe(false)
  })

  it('always ends with properties, and always offers refresh', () => {
    const entries = contextMenuActions(object())
    expect(ids(entries)).toContain('refresh')
    expect(entries.at(-1)).toMatchObject({ id: 'properties' })
  })

  it('never places a separator first or last, where it would draw against the border', () => {
    for (const type of ['user', 'group', 'organizational_unit']) {
      const entries = contextMenuActions(
        object({ type: type as DirectoryObject['type'], is_container: type === 'organizational_unit' }),
      )
      expect(entries[0]?.kind).not.toBe('separator')
      expect(entries.at(-1)?.kind).not.toBe('separator')
    }
  })
})

describe('the two surfaces agree', () => {
  it('offers the menu everything the button row offers', () => {
    for (const type of ['user', 'computer', 'group', 'organizational_unit']) {
      const shape = { type: type as DirectoryObject['type'], is_container: type === 'organizational_unit' }
      const row = ids(detailRowActions(object(shape), UNKNOWN))
      const inMenu = ids(contextMenuActions(object(shape)))
      for (const id of row) expect(inMenu).toContain(id)
    }
  })

  it('marks deletion as destructive in both', () => {
    const row = detailRowActions(object(), UNKNOWN).find((entry) => entry.id === 'delete')
    const menu = contextMenuActions(object()).find(
      (entry) => entry.kind === 'item' && entry.id === 'delete',
    )
    expect(row?.danger).toBe(true)
    expect(menu && 'danger' in menu && menu.danger).toBe(true)
  })
})
