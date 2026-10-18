import { describe, expect, it } from 'vitest'

import type { DirectoryObject } from '../../../api/types'
import {
  EMPTY_DRAFT,
  changesOf,
  countChanges,
  fromDateInput,
  passwordSteps,
  toDateInput,
  withAceRemovalToggled,
  withAclAdded,
  withAclAddDropped,
  withMemberAdded,
  withMemberRemoved,
  withRawAttribute,
  withoutApplied,
  type AclAdd,
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

const anna = { ...obj('CN=Anna,OU=u'), sid: 'S-1-5-21-1-2-3-1105' } as DirectoryObject
const ACE: AclAdd = { kind: 'ace', trustee: anna, preset: 'read', mask: 0x20014, deny: false, inherit: true }
const DELEGATION: AclAdd = { kind: 'delegate', trustee: anna, templateId: 'reset_password' }
const SDDL = 'O:DAG:DAD:AI(A;;RP;;;WD)'

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
      raw: { info: { before: [], after: ['note'] } },
      aclAdd: [ACE],
      aclRemove: [3],
      aclSddl: 'O:DA',
    }
    expect(countChanges(changesOf(draft, BASE))).toBe(15)
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
    raw: { info: { before: [], after: ['note'] } },
    aclAdd: [ACE],
    aclRemove: [3],
    aclSddl: 'O:DA',
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
      'attributes', 'rawAttributes', 'acl', 'accountExpires', 'mustChangePassword', 'unlock', 'deleteProtected', 'group', 'memberAdd', 'memberRemove', 'primaryGroup', 'certificates',
    ])
    expect(countChanges(changesOf(left, BASE))).toBe(0)
  })
})

describe('the Security tab in the draft', () => {
  // A tester found the tab writing the moment an entry was removed. It now
  // queues, like every other tab, and OK or Apply writes it in one go.

  it('queues an entry and remembers the permissions it was queued against', () => {
    const next = withAclAdded(EMPTY_DRAFT, ACE, SDDL)
    expect(next.aclAdd).toEqual([ACE])
    expect(next.aclSddl).toBe(SDDL)
  })

  it('queues the same entry once', () => {
    const once = withAclAdded(EMPTY_DRAFT, ACE, SDDL)
    expect(withAclAdded(once, { ...ACE }, SDDL).aclAdd).toHaveLength(1)
    expect(withAclAdded(once, DELEGATION, SDDL).aclAdd).toHaveLength(2)
  })

  it('drops a queued entry again', () => {
    const two = withAclAdded(withAclAdded(EMPTY_DRAFT, ACE, SDDL), DELEGATION, SDDL)
    expect(withAclAddDropped(two, 0).aclAdd).toEqual([DELEGATION])
  })

  it('marks an entry for removal, and a second click takes the mark back', () => {
    const marked = withAceRemovalToggled(EMPTY_DRAFT, 2, SDDL)
    expect(marked.aclRemove).toEqual([2])
    expect(withAceRemovalToggled(marked, 2, SDDL).aclRemove).toEqual([])
  })

  it('keeps the permissions it first saw, so a later change by someone else is caught', () => {
    const first = withAceRemovalToggled(EMPTY_DRAFT, 0, SDDL)
    expect(withAclAdded(first, ACE, 'O:DAG:DAD:(A;;RP;;;AU)').aclSddl).toBe(SDDL)
  })

  it('sends removals, additions and what they were made against', () => {
    const draft = withAclAdded(withAceRemovalToggled(EMPTY_DRAFT, 1, SDDL), DELEGATION, SDDL)
    expect(changesOf(draft, BASE).acl).toEqual({ expectedSddl: SDDL, remove: [1], add: [DELEGATION] })
    expect(countChanges(changesOf(draft, BASE))).toBe(2)
  })

  it('sends nothing for the tab once every mark was taken back', () => {
    const draft = withAceRemovalToggled(withAceRemovalToggled(EMPTY_DRAFT, 1, SDDL), 1, SDDL)
    expect(changesOf(draft, BASE).acl).toBeUndefined()
  })

  it('is forgotten once written', () => {
    const draft = withAclAdded(withAceRemovalToggled(EMPTY_DRAFT, 1, SDDL), ACE, SDDL)
    const left = withoutApplied(draft, ['acl'])
    expect(left.aclAdd).toEqual([])
    expect(left.aclRemove).toEqual([])
    expect(left.aclSddl).toBeUndefined()
  })
})

describe('the attribute editor in the draft', () => {
  it('queues a changed value against what the editor showed', () => {
    const next = withRawAttribute(EMPTY_DRAFT, 'info', ['old'], ['new'])
    expect(changesOf(next, BASE).raw).toEqual({ info: 'new' })
  })

  it('sends several values as a list, and none as a removal', () => {
    const many = withRawAttribute(EMPTY_DRAFT, 'otherTelephone', [], ['1', '2'])
    expect(changesOf(many, BASE).raw).toEqual({ otherTelephone: ['1', '2'] })
    const none = withRawAttribute(EMPTY_DRAFT, 'info', ['old'], [])
    expect(changesOf(none, BASE).raw).toEqual({ info: null })
  })

  it('forgets an edit that ends where it started', () => {
    const edited = withRawAttribute(EMPTY_DRAFT, 'info', ['old'], ['new'])
    const back = withRawAttribute(edited, 'info', ['new'], ['old'])
    expect(back.raw).toEqual({})
    expect(changesOf(back, BASE).raw).toBeUndefined()
  })

  it('keeps what the editor first showed when the same attribute is edited twice', () => {
    const twice = withRawAttribute(withRawAttribute(EMPTY_DRAFT, 'info', ['old'], ['a']), 'info', ['a'], ['b'])
    expect(twice.raw.info).toEqual({ before: ['old'], after: ['b'] })
  })

  it('counts each attribute once, and is forgotten once written', () => {
    const draft = withRawAttribute(withRawAttribute(EMPTY_DRAFT, 'info', [], ['x']), 'comment', [], ['y'])
    expect(countChanges(changesOf(draft, BASE))).toBe(2)
    expect(withoutApplied(draft, ['rawAttributes']).raw).toEqual({})
  })
})

describe('"User cannot change password" in the draft', () => {
  const base: SheetBase = { ...BASE, cannotChangePassword: false }

  it('is sent only when it changed', () => {
    expect(changesOf({ ...EMPTY_DRAFT, cannotChangePassword: false }, base).cannotChangePassword).toBeUndefined()
    const changes = changesOf({ ...EMPTY_DRAFT, cannotChangePassword: true }, base)
    expect(changes.cannotChangePassword).toBe(true)
    expect(countChanges(changes)).toBe(1)
  })

  it('is forgotten once written', () => {
    const left = withoutApplied({ ...EMPTY_DRAFT, cannotChangePassword: true }, ['cannotChangePassword'])
    expect(left.cannotChangePassword).toBeUndefined()
  })
})

describe('the order the two password options are written in', () => {
  // The server refuses "must change" while "cannot change" is set, and the
  // other way round; switching from one to the other clears before it sets.
  it('clears "must change" before setting "cannot change"', () => {
    expect(passwordSteps({ mustChangePassword: false, cannotChangePassword: true })).toEqual([
      'mustChangePassword',
      'cannotChangePassword',
    ])
  })

  it('clears "cannot change" before setting "must change"', () => {
    expect(passwordSteps({ mustChangePassword: true, cannotChangePassword: false })).toEqual([
      'cannotChangePassword',
      'mustChangePassword',
    ])
  })

  it('writes only what changed', () => {
    expect(passwordSteps({ cannotChangePassword: true })).toEqual(['cannotChangePassword'])
    expect(passwordSteps({})).toEqual([])
  })
})
