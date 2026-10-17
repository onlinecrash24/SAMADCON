/**
 * The common options of a preference item, and conditions picked for its
 * targeting — the rules GPMC's own dialog follows, so the form cannot offer a
 * combination the server would refuse.
 *
 * Measured on the reference GPO "SAMADCON-Referenz-ILT": ticking "remove this
 * item when it is no longer applied" turned the action into Replace, and GPMC
 * greys "apply once" out while removal is ticked (and the other way round).
 */

import type {
  PreferenceAction,
  PreferenceOptions,
  TargetCondition,
  TargetConditionType,
} from '../../../api/types'

export const NO_OPTIONS: PreferenceOptions = {
  stop_on_error: false,
  user_context: false,
  remove_policy: false,
  run_once: false,
}

export function setOption(
  options: PreferenceOptions,
  action: PreferenceAction | undefined,
  name: keyof PreferenceOptions,
  value: boolean,
): { options: PreferenceOptions; action: PreferenceAction | undefined } {
  const next = { ...options, [name]: value }
  if (value && name === 'remove_policy') next.run_once = false
  if (value && name === 'run_once') next.remove_policy = false
  return {
    options: next,
    action: value && name === 'remove_policy' && action !== undefined ? 'R' : action,
  }
}

interface Picked {
  dn: string
  name: string
  sam_account_name?: string | null
  sid?: string | null
}

/**
 * A condition for an object picked in the directory. The server reads name
 * and SID again from the DN; these are what the form shows meanwhile.
 */
export function conditionFromObject(
  type: TargetConditionType,
  object: Picked,
  netbios: string,
): TargetCondition {
  const base = { type, bool: 'AND' as const, not: false, dn: object.dn }
  const account = object.sam_account_name ?? object.name
  switch (type) {
    case 'group':
      return {
        ...base,
        name: netbios ? `${netbios}\\${account}` : account,
        sid: object.sid ?? '',
        user_context: true,
        primary_group: false,
        local_group: false,
      }
    case 'user':
      return { ...base, name: netbios ? `${netbios}\\${account}` : account, sid: object.sid ?? '' }
    case 'ou':
      return { ...base, name: object.dn, user_context: true, direct_member: false }
    case 'computer':
      return { ...base, name: account.replace(/\$$/, ''), computer_type: 'NETBIOS' }
  }
}
