import { describe, expect, it } from 'vitest'

import type { DirectoryObject } from '../../../api/types'
import {
  EMPTY_DRAFT,
  changesOf,
  countChanges,
  fromDateInput,
  toDateInput,
  withMemberAdded,
  withMemberRemoved,
  withoutApplied,
  type Draft,
  type SheetBase,
} from './draft'

const BASE: SheetBase = {
  attributes: { first_name: 'Anna', description: '', mail: null },
  flags: { account_disabled: false, password_never_expires: true },
  accountExpires: null,
  mustChangePassword: false,
  deleteProtected: false,
}

const obj = (dn: string): DirectoryObject =>
  ({ dn, name: dn.split(',')[0]!.slice(3), type: 'group' }) as DirectoryObject

describe('what a draft would send', () => {
  it('is nothing when nothing was touched', () => {
    const c = changesOf(EMPTY_DRAFT, BASE)
    expect(countChanges(c)).toBe(0)
    expect(c.attributes).toBeUndefined()
    expect(c.flags).toBeUndefined()
  })

  it('is nothing when a field was retyped to what it was', () => {
    const draft: Draft = { ...EMPTY_DRAFT, attributes: { first_name: ' Anna ' }, flags: { password_never_expires: true } }
    expect(countChanges(changesOf(draft, BASE))).toBe(0)
  })

  it('turns an emptied field into a removal', () => {
    const draft: Draft = { ...EMPTY_DRAFT, attributes: { first_name: '  ' } }
    expect(changesOf(draft, BASE).attributes).toEqual({ first_name: null })
  })

  it('compares a list in order and sends it whole', () => {
    const base = { ...BASE, attributes: { ...BASE.attributes, other_telephone: ['1', '2'] } }
    expect(changesOf({ ...EMPTY_DRAFT, attributes: { other_telephone: [' 1 ', '2', ''] } }, base).attributes).toBeUndefined()
    expect(changesOf({ ...EMPTY_DRAFT, attributes: { other_telephone: ['2', '1'] } }, base).attributes).toEqual({ other_telephone: ['2', '1'] })
    expect(changesOf({ ...EMPTY_DRAFT, attributes: { other_telephone: [] } }, base).attributes).toEqual({ other_telephone: null })
    // A list where the directory had none is a change; an empty one where it had none is not.
    expect(changesOf({ ...EMPTY_DRAFT, attributes: { other_pager: ['x'] } }, base).attributes).toEqual({ other_pager: ['x'] })
    expect(changesOf({ ...EMPTY_DRAFT, attributes: { other_pager: [] } }, base).attributes).toBeUndefined()
  })

  it('sends a flag only when it flipped', () => {
    const draft: Draft = { ...EMPTY_DRAFT, flags: { account_disabled: true, password_never_expires: true } }
    expect(changesOf(draft, BASE).flags).toEqual({ account_disabled: true })
  })

  it('reads the expiry the way ADUC does: the end of the chosen day', () => {
    const draft: Draft = { ...EMPTY_DRAFT, accountExpires: '2026-10-05' }
    expect(changesOf(draft, BASE).accountExpires).toBe('2026-10-05T23:59:59.000Z')
    // Cleared means never, which the API spells null — and only if it was not never already.
    expect(changesOf({ ...EMPTY_DRAFT, accountExpires: '' }, BASE).accountExpires).toBeUndefined()
    expect(
      changesOf({ ...EMPTY_DRAFT, accountExpires: '' }, { ...BASE, accountExpires: '2026-01-01T00:00:00Z' })
        .accountExpires,
    ).toBeNull()
  })

  it('round-trips a date through the input format', () => {
    expect(toDateInput('2026-10-05T23:59:59Z')).toBe('2026-10-05')
    expect(toDateInput(null)).toBe('')
    expect(toDateInput('garbage')).toBe('')
    expect(fromDateInput('')).toBeNull()
  })

  it('sends the primary group only when it is a different one', () => {
    const base = { ...BASE, primaryGroup: 'CN=Domain Users,CN=Users,DC=x' }
    expect(changesOf({ ...EMPTY_DRAFT, primaryGroup: 'cn=domain users,cn=users,dc=x' }, base).primaryGroup).toBeUndefined()
    expect(changesOf({ ...EMPTY_DRAFT, primaryGroup: 'CN=Staff,DC=x' }, base).primaryGroup).toBe('CN=Staff,DC=x')
  })

  it('counts everything Apply would do', () => {
    const draft: Draft = {
      attributes: { first_name: 'Berta', description: 'x' },
      flags: { account_disabled: true },
      accountExpires: '2026-10-05',
      mustChangePassword: true,
      unlock: true,
      deleteProtected: true,
      memberAdd: [obj('CN=A,OU=g')],
      memberRemove: ['CN=B,OU=g'],
      primaryGroup: 'CN=A,OU=g',
      certAdd: [{ data: 'AA==', info: { fingerprint: 'f1', subject: 'x', issuer: 'y', der: 'AA==' } }],
      certRemove: ['f0'],
    }
    expect(countChanges(changesOf(draft, BASE))).toBe(12)
  })
})

describe('membership edits in the draft', () => {
  it('queues an add, once', () => {
    const a = obj('CN=A,OU=g')
    const once = withMemberAdded(EMPTY_DRAFT, a)
    expect(withMemberAdded(once, a).memberAdd).toHaveLength(1)
  })

  it('adding something queued for removal just un-removes it', () => {
    const queued: Draft = { ...EMPTY_DRAFT, memberRemove: ['CN=A,OU=g'] }
    const next = withMemberAdded(queued, obj('cn=a,ou=g'))
    expect(next.memberRemove).toEqual([])
    expect(next.memberAdd).toEqual([])
  })

  it('removing something queued for adding just un-adds it', () => {
    const queued = withMemberAdded(EMPTY_DRAFT, obj('CN=A,OU=g'))
    const next = withMemberRemoved(queued, 'CN=A,OU=g', false)
    expect(next.memberAdd).toEqual([])
    expect(next.memberRemove).toEqual([])
  })

  it('queues a removal only for a current member', () => {
    expect(withMemberRemoved(EMPTY_DRAFT, 'CN=X,OU=g', false).memberRemove).toEqual([])
    expect(withMemberRemoved(EMPTY_DRAFT, 'CN=X,OU=g', true).memberRemove).toEqual(['CN=X,OU=g'])
  })
})

describe('after a partial apply', () => {
  const full: Draft = {
    attributes: { first_name: 'Berta' },
    flags: { account_disabled: true },
    accountExpires: '2026-10-05',
    mustChangePassword: true,
    unlock: true,
    deleteProtected: true,
    scope: 'universal',
    securityGroup: false,
    memberAdd: [obj('CN=A,OU=g')],
    memberRemove: ['CN=B,OU=g'],
    primaryGroup: 'CN=A,OU=g',
    certAdd: [{ data: 'AA==', info: { fingerprint: 'f1', subject: 'x', issuer: 'y', der: 'AA==' } }],
    certRemove: ['f0'],
  }

  it('drops what was written and keeps what was not', () => {
    const left = withoutApplied(full, ['attributes', 'accountExpires'])
    expect(left.attributes).toEqual({})
    expect(left.flags).toEqual({})
    expect(left.accountExpires).toBeUndefined()
    // Untouched by the two steps that ran:
    expect(left.mustChangePassword).toBe(true)
    expect(left.memberAdd).toHaveLength(1)
    expect(left.memberRemove).toHaveLength(1)
  })

  it('is empty once every step ran', () => {
    const left = withoutApplied(full, [
      'attributes', 'accountExpires', 'mustChangePassword', 'unlock', 'deleteProtected', 'group', 'memberAdd', 'memberRemove', 'primaryGroup', 'certificates',
    ])
    expect(countChanges(changesOf(left, BASE))).toBe(0)
  })
})
