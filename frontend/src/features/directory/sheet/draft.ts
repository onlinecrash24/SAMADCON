/**
 * The draft behind a property sheet: everything typed or ticked since it was
 * opened, held until OK or Apply, and compared against what the directory
 * said when the sheet was loaded.
 *
 * One draft for the whole window rather than one per tab, and nothing is
 * written until asked. That is the way ADUC works and the way testers who
 * used this in production asked for it: a checkbox that wrote the moment it
 * was ticked, beside a text field that waited for a button, was two rules for
 * one window, and the difference was invisible until something had already
 * changed.
 *
 * Pure: no React, no API, so the comparison can be tested on its own. The
 * sheet component holds one of these in state and asks `changesOf` what, if
 * anything, has to be sent.
 */

import type { DirectoryObject } from '../../../api/types'

/** What the directory said when the sheet opened — the thing a draft is against. */
export interface SheetBase {
  attributes: Record<string, string | null>
  flags?: Record<string, boolean>
  /** ISO timestamp, or null for "never". Undefined when the type has none. */
  accountExpires?: string | null
  mustChangePassword?: boolean
  deleteProtected?: boolean
  /** Groups only. */
  scope?: string | null
  securityGroup?: boolean
}

export interface Draft {
  attributes: Record<string, string>
  flags: Record<string, boolean>
  /** yyyy-mm-dd, or '' for "never". Absent until touched. */
  accountExpires?: string
  mustChangePassword?: boolean
  /** ADUC's "Unlock account" box: an action, queued like everything else. */
  unlock?: boolean
  deleteProtected?: boolean
  scope?: string
  securityGroup?: boolean
  /** Objects to add to, and DNs to take out of, the membership this sheet shows. */
  memberAdd: DirectoryObject[]
  memberRemove: string[]
}

export const EMPTY_DRAFT: Draft = {
  attributes: {},
  flags: {},
  memberAdd: [],
  memberRemove: [],
}

/** What has to be sent: only the parts that differ from the base. */
export interface Changes {
  attributes?: Record<string, string | null>
  flags?: Record<string, boolean>
  /** ISO timestamp for the end of the chosen day, or null for "never". */
  accountExpires?: string | null
  mustChangePassword?: boolean
  unlock?: boolean
  deleteProtected?: boolean
  scope?: string
  securityGroup?: boolean
  memberAdd: DirectoryObject[]
  memberRemove: string[]
}

/** ISO timestamp → yyyy-mm-dd for <input type="date">, or '' when unset. */
export function toDateInput(value: string | null | undefined): string {
  if (!value) return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toISOString().slice(0, 10)
}

/**
 * yyyy-mm-dd → the end of that day, UTC, as the account's expiry; '' → null.
 *
 * The end of the day rather than its start: "expires on the 5th" means the
 * 5th is the last day it works, which is also how ADUC reads the date.
 */
export function fromDateInput(value: string): string | null {
  return value ? new Date(`${value}T23:59:59Z`).toISOString() : null
}

export function changesOf(draft: Draft, base: SheetBase): Changes {
  const attributes: Record<string, string | null> = {}
  for (const [name, next] of Object.entries(draft.attributes)) {
    const current = base.attributes[name] ?? ''
    const trimmed = next.trim()
    if (trimmed === current) continue
    // An emptied field means "remove the attribute": null, not ''.
    attributes[name] = trimmed === '' ? null : trimmed
  }

  const flags: Record<string, boolean> = {}
  for (const [name, next] of Object.entries(draft.flags)) {
    if (Boolean(base.flags?.[name]) !== next) flags[name] = next
  }

  const out: Changes = {
    memberAdd: draft.memberAdd,
    memberRemove: draft.memberRemove,
  }
  if (Object.keys(attributes).length) out.attributes = attributes
  if (Object.keys(flags).length) out.flags = flags

  if (draft.accountExpires !== undefined && draft.accountExpires !== toDateInput(base.accountExpires)) {
    out.accountExpires = fromDateInput(draft.accountExpires)
  }
  if (draft.mustChangePassword !== undefined && draft.mustChangePassword !== Boolean(base.mustChangePassword)) {
    out.mustChangePassword = draft.mustChangePassword
  }
  if (draft.unlock) out.unlock = true
  if (draft.deleteProtected !== undefined && draft.deleteProtected !== Boolean(base.deleteProtected)) {
    out.deleteProtected = draft.deleteProtected
  }
  if (draft.scope !== undefined && draft.scope !== (base.scope ?? '')) {
    out.scope = draft.scope
  }
  if (draft.securityGroup !== undefined && draft.securityGroup !== Boolean(base.securityGroup)) {
    out.securityGroup = draft.securityGroup
  }
  return out
}

/** How many things Apply would do — for the footer, and for "is Apply enabled". */
export function countChanges(changes: Changes): number {
  return (
    Object.keys(changes.attributes ?? {}).length +
    Object.keys(changes.flags ?? {}).length +
    (changes.accountExpires !== undefined ? 1 : 0) +
    (changes.mustChangePassword !== undefined ? 1 : 0) +
    (changes.unlock ? 1 : 0) +
    (changes.deleteProtected !== undefined ? 1 : 0) +
    (changes.scope !== undefined ? 1 : 0) +
    (changes.securityGroup !== undefined ? 1 : 0) +
    changes.memberAdd.length +
    changes.memberRemove.length
  )
}

/**
 * The draft with a membership edit folded in.
 *
 * Adding something that is queued for removal un-removes it instead of
 * queuing an add, and vice versa: the sheet shows one list, and a DN cannot
 * be both leaving and joining it.
 */
export function withMemberAdded(draft: Draft, object: DirectoryObject): Draft {
  const lower = object.dn.toLowerCase()
  if (draft.memberRemove.some((dn) => dn.toLowerCase() === lower)) {
    return { ...draft, memberRemove: draft.memberRemove.filter((dn) => dn.toLowerCase() !== lower) }
  }
  if (draft.memberAdd.some((o) => o.dn.toLowerCase() === lower)) return draft
  return { ...draft, memberAdd: [...draft.memberAdd, object] }
}

export function withMemberRemoved(draft: Draft, dn: string, existing: boolean): Draft {
  const lower = dn.toLowerCase()
  if (draft.memberAdd.some((o) => o.dn.toLowerCase() === lower)) {
    return { ...draft, memberAdd: draft.memberAdd.filter((o) => o.dn.toLowerCase() !== lower) }
  }
  // Only something that is actually a member today can be queued for removal.
  if (!existing || draft.memberRemove.some((d) => d.toLowerCase() === lower)) return draft
  return { ...draft, memberRemove: [...draft.memberRemove, dn] }
}

/**
 * The draft after part of it was applied: those parts are dropped, the rest
 * stays. Apply writes in steps, and a step that failed leaves everything
 * after it untouched; what the person typed there must not be lost.
 */
export type Step =
  | 'attributes'
  | 'accountExpires'
  | 'mustChangePassword'
  | 'unlock'
  | 'deleteProtected'
  | 'group'
  | 'memberAdd'
  | 'memberRemove'

export function withoutApplied(draft: Draft, applied: Step[]): Draft {
  let next = draft
  for (const step of applied) {
    switch (step) {
      case 'attributes':
        next = { ...next, attributes: {}, flags: {} }
        break
      case 'accountExpires': {
        const { accountExpires: _drop, ...rest } = next
        next = rest as Draft
        break
      }
      case 'mustChangePassword': {
        const { mustChangePassword: _drop, ...rest } = next
        next = rest as Draft
        break
      }
      case 'unlock': {
        const { unlock: _drop, ...rest } = next
        next = rest as Draft
        break
      }
      case 'deleteProtected': {
        const { deleteProtected: _drop, ...rest } = next
        next = rest as Draft
        break
      }
      case 'group': {
        const { scope: _s, securityGroup: _g, ...rest } = next
        next = rest as Draft
        break
      }
      case 'memberAdd':
        next = { ...next, memberAdd: [] }
        break
      case 'memberRemove':
        next = { ...next, memberRemove: [] }
        break
    }
  }
  return next
}
