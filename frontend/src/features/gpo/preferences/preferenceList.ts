/**
 * The items of one preference type, as a list and as what is sent back.
 *
 * The editor shows them as GPMC does — a table, the item opened in a window
 * — and every change is saved at once, the whole list, as the file holds it.
 * These functions are that list's arithmetic: replace, append, move, remove,
 * and what an item sends. None of them changes the list it is given.
 */

import type {
  PreferenceAction,
  PreferenceItem,
  PreferenceKind,
  PreferenceMember,
  PreferenceOptions,
  TargetCondition,
} from '../../../api/types'
import { NO_OPTIONS } from './preferenceOptions'

/** One item as the form holds it. */
export interface Draft {
  kind: string
  uid?: string
  /** Absent for a service, which has no Create/Replace/Update/Delete. */
  action?: PreferenceAction
  properties: Record<string, string>
  values?: string[]
  members?: PreferenceMember[]
  options: PreferenceOptions
  /** Null when the targeting holds something only GPMC edits; then it is not sent. */
  targeting: TargetCondition[] | null
  /** Read only, for the list and the window's title. */
  name: string
  filter_names: string[]
  has_password: boolean
}

export function toDraft(item: PreferenceItem): Draft {
  return {
    kind: item.kind,
    uid: item.uid,
    action: item.action ? (item.action as PreferenceAction) : undefined,
    properties: { ...item.properties },
    values: item.values,
    members: item.members,
    options: item.options ?? NO_OPTIONS,
    targeting: item.targeting?.editable ? item.targeting.conditions : null,
    name: item.name,
    filter_names: item.filter_names,
    has_password: item.has_password,
  }
}

export function blank(kind: PreferenceKind): Draft {
  const properties: Record<string, string> = {}
  for (const field of kind.fields) properties[field.name] = field.default
  return {
    kind: kind.id,
    action: kind.has_action ? 'C' : undefined,
    properties,
    values: [],
    members: [],
    options: NO_OPTIONS,
    targeting: [],
    name: '',
    filter_names: [],
    has_password: false,
  }
}

/** The list with *item* at *index*, or appended when index is null. */
export function withItem(list: Draft[], index: number | null, item: Draft): Draft[] {
  if (index === null) return [...list, item]
  return list.map((entry, at) => (at === index ? item : entry))
}

/** The list with one item moved by *delta*; the same list if it cannot move. */
export function moved(list: Draft[], index: number, delta: number): Draft[] {
  const target = index + delta
  if (target < 0 || target >= list.length || index < 0 || index >= list.length) return list
  const next = [...list]
  const [item] = next.splice(index, 1)
  next.splice(target, 0, item as Draft)
  return next
}

export function without(list: Draft[], index: number): Draft[] {
  return list.filter((_, at) => at !== index)
}

/**
 * What the server is sent: never the display-only parts, never raw filters,
 * and targeting only where it was editable — the server carries the rest.
 */
export function toPayload(list: Draft[]) {
  return list.map(({ kind, uid, action, properties, values, members, options, targeting }) => ({
    kind,
    uid,
    action,
    properties,
    values,
    members,
    options,
    ...(targeting === null ? {} : { targeting: { conditions: targeting } }),
  }))
}

/** What the list shows beside the name — GPMC's column for the type. */
export function itemSummary(kind: string, properties: Record<string, string>): string {
  const value = (name: string) => (properties[name] ?? '').trim()
  switch (kind) {
    case 'drive':
    case 'folder':
    case 'shared':
    case 'local':
      return value('path')
    case 'file':
    case 'shortcut':
      return value('targetPath')
    case 'environment':
      return value('value')
    case 'port':
      return value('ipAddress') || value('path')
    case 'group':
    case 'user':
      return value('description')
    case 'service':
      return value('startupType')
    case 'task':
    case 'immediate':
      return value('appName')
    case 'task_v2':
    case 'immediate_v2':
      return value('runAs')
    case 'registry': {
      const key = value('key').replace(/^\\+/, '')
      const path = [value('hive'), key].filter(Boolean).join('\\')
      return value('name') ? `${path} › ${value('name')}` : path
    }
    default:
      return ''
  }
}
