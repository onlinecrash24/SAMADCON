/**
 * Which groups a copy offers, and which it asks for.
 *
 * Pure, so the one rule that is easy to get wrong can be tested without a
 * browser: the primary group is not in memberOf — membership in it is
 * implied — and a template whose primary group is not Domain Users would
 * otherwise lose it silently.
 */

import type { UserDetail } from '../../api/types'

export const DOMAIN_USERS_RID = 513

/** The template's groups, as the copy dialog lists them. */
export function templateGroups(template: Pick<UserDetail, 'member_of' | 'primary_group_id' | 'primary_group_dn'>): string[] {
  const groups = [...template.member_of]
  const primary = template.primary_group_dn
  if (
    primary &&
    template.primary_group_id !== DOMAIN_USERS_RID &&
    !groups.some((group) => group.toLowerCase() === primary.toLowerCase())
  ) {
    groups.push(primary)
  }
  return groups
}

/**
 * What to send as `groups`. Nothing left out means nothing is sent, and the
 * server takes all of the template's groups — which is also right when the
 * template gained a group after the dialog was opened.
 */
export function requestedGroups(groups: string[], leftOut: ReadonlySet<string>): string[] | undefined {
  if (leftOut.size === 0) return undefined
  return groups.filter((group) => !leftOut.has(group.toLowerCase()))
}
