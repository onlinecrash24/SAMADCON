/**
 * Recognising the server's refusal to disable an administrator by one click.
 *
 * The server decides who counts — the built-in Administrator by its RID, and
 * anyone in Domain, Schema or Enterprise Admins with nesting resolved — and
 * says so with one error code. Every place that can disable an account
 * catches that code and asks; none of them has to know who is an
 * administrator, which is why none of them can get it wrong.
 */

import { ApiError } from '../../api/client'

export const CONFIRM_DISABLE_ADMIN = 'confirm_disable_admin'
export const CONFIRM_DELETE_ADMIN = 'confirm_delete_admin'

export interface AdminRefusal {
  /** What was refused. */
  action: 'disable' | 'delete'
  /** "Administrator" for the built-in account, else the admin group's name. */
  role: string
  /** The logon name, which is what samba-tool takes. */
  account: string | null
}

export function adminRefusal(error: unknown): AdminRefusal | null {
  if (!(error instanceof ApiError)) return null
  if (error.code !== CONFIRM_DISABLE_ADMIN && error.code !== CONFIRM_DELETE_ADMIN) return null
  const role = error.context?.role
  const account = error.context?.account
  return {
    action: error.code === CONFIRM_DELETE_ADMIN ? 'delete' : 'disable',
    role: typeof role === 'string' ? role : '',
    account: typeof account === 'string' && account ? account : null,
  }
}

/** Whether the refusal is about the built-in account rather than a membership. */
export function isBuiltinAdministrator(refusal: AdminRefusal): boolean {
  return refusal.role === 'Administrator'
}
