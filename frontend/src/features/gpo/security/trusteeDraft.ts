/**
 * The accounts on one card of the security settings — a user right, or the
 * members of a restricted group — while they are being edited.
 *
 * The card holds them until Save and drops them on Discard, as the cards
 * beside it do. Each account picked or removed used to be written at once.
 * SIDs are compared without regard to case, and order does not matter: the
 * policy is a set of accounts.
 */

import type { SecurityTrustee } from '../../../api/types'

const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase()

export function withTrustee(list: SecurityTrustee[], trustee: SecurityTrustee): SecurityTrustee[] {
  return list.some((entry) => same(entry.sid, trustee.sid)) ? list : [...list, trustee]
}

export function withoutTrustee(list: SecurityTrustee[], sid: string): SecurityTrustee[] {
  return list.filter((entry) => !same(entry.sid, sid))
}

export function trusteesChanged(saved: SecurityTrustee[], current: SecurityTrustee[]): boolean {
  const key = (list: SecurityTrustee[]) =>
    list
      .map((entry) => entry.sid.toLowerCase())
      .sort()
      .join('|')
  return key(saved) !== key(current)
}

/** What Save sends: the SIDs, or null to drop the setting once nobody is left. */
export function trusteeValue(current: SecurityTrustee[]): string[] | null {
  return current.length ? current.map((entry) => entry.sid) : null
}
