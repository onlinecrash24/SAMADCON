/**
 * What can be done to a directory object — said once, for everyone who asks.
 *
 * Until now the only place that knew was the row of buttons in the detail
 * pane. A right-click menu needs the same answer, and two lists of "what
 * applies to a computer" drift apart the week after they are written: someone
 * adds an action to one, and the other quietly keeps offering the old set.
 *
 * So this returns plain descriptions and nothing else — no React, no
 * translation, no calls. The caller maps an id to behaviour, which is the part
 * that genuinely differs: the detail pane already has the object loaded and
 * can mutate it directly, and the menu has a row and a DN.
 *
 * Being pure is also what makes it the one piece of this work that can be
 * checked without a browser, which matters for the thing two screens share.
 */

import type { DirectoryObject } from '../../api/types'
import type { MessageKey } from '../../i18n/messages'

export type ActionId =
  | 'open'
  | 'refresh'
  | 'newUser'
  | 'newGroup'
  | 'newComputer'
  | 'newOu'
  | 'enable'
  | 'disable'
  | 'unlock'
  | 'resetPassword'
  | 'resetAccount'
  | 'rename'
  | 'move'
  | 'delete'
  | 'properties'

export interface ActionItem {
  kind: 'item'
  id: ActionId
  labelKey: MessageKey
  /** Drawn as destructive, and never the first thing the keyboard lands on. */
  danger?: boolean
}

export interface ActionSubmenu {
  kind: 'submenu'
  labelKey: MessageKey
  items: ActionItem[]
}

export type MenuEntry = ActionItem | ActionSubmenu | { kind: 'separator' }

/**
 * What is known about an account beyond what its row carries.
 *
 * `null` means "not loaded", which is the normal case for a list row and is
 * treated differently per field — see the two builders below.
 */
export interface AccountFacts {
  disabled: boolean | null
  lockedOut: boolean | null
}

export const UNKNOWN: AccountFacts = { disabled: null, lockedOut: null }

/** Users and the managed service accounts that behave like them. */
function isAccount(type: string): boolean {
  return type === 'user' || type === 'managed_service_account'
}

/** Containers that can be created into. */
function canHoldNewObjects(object: DirectoryObject): boolean {
  return object.is_container
}

const item = (id: ActionId, labelKey: MessageKey, danger?: boolean): ActionItem => ({
  kind: 'item',
  id,
  labelKey,
  ...(danger && { danger }),
})

/**
 * The actions that act on the object itself, in the order both surfaces show
 * them. Everything below is assembled from this.
 */
function objectActions(object: DirectoryObject, facts: AccountFacts): ActionItem[] {
  const actions: ActionItem[] = []

  if (isAccount(object.type)) {
    // The row already carries `disabled`, so this needs nothing loaded. Where
    // something *is* loaded it wins, because it is fresher than the row.
    const disabled = facts.disabled ?? object.disabled ?? false
    actions.push(item(disabled ? 'enable' : 'disable', disabled ? 'action.enable' : 'action.disable'))

    // The only field a row genuinely cannot know. Loaded, the answer is
    // precise. Unloaded, the action is offered anyway and reports what
    // happened: an absent "Entsperren" is indistinguishable from an account
    // that is not locked, which is the wrong thing to leave someone guessing.
    if (facts.lockedOut !== false) actions.push(item('unlock', 'action.unlock'))

    actions.push(item('resetPassword', 'action.resetPassword'))
  }

  if (object.type === 'computer') actions.push(item('resetAccount', 'action.resetAccount'))

  actions.push(item('rename', 'action.rename'))
  // Every object, not only OUs: move_object is generic, and a user in the
  // wrong OU is the commoner mistake.
  actions.push(item('move', 'action.move'))
  actions.push(item('delete', 'action.delete', true))

  return actions
}

/** The row of buttons in the detail pane, which has the object loaded. */
export function detailRowActions(object: DirectoryObject, facts: AccountFacts): ActionItem[] {
  return objectActions(object, facts)
}

/**
 * The right-click menu, which has a row and nothing else.
 *
 * Shaped like the menu in ADUC: open and refresh, then what can be created
 * here, then what can be done to this object, then its properties last.
 */
export function contextMenuActions(object: DirectoryObject, facts = UNKNOWN): MenuEntry[] {
  const entries: MenuEntry[] = []

  if (object.is_container) entries.push(item('open', 'action.open'))
  entries.push(item('refresh', 'action.refresh'))

  if (canHoldNewObjects(object)) {
    entries.push({ kind: 'separator' })
    entries.push({
      // One level of submenu, and only for this. It exists because "Neu" is
      // how the original groups four commands that would otherwise double the
      // height of every menu. A second level would triple the positioning,
      // hover-intent and keyboard code; add a flat item instead.
      kind: 'submenu',
      labelKey: 'action.new',
      items: [
        item('newUser', 'action.newUser'),
        item('newGroup', 'action.newGroup'),
        item('newComputer', 'action.newComputer'),
        item('newOu', 'action.newOu'),
      ],
    })
  }

  entries.push({ kind: 'separator' })
  for (const action of objectActions(object, facts)) entries.push(action)

  entries.push({ kind: 'separator' })
  entries.push(item('properties', 'action.properties'))

  return entries
}
