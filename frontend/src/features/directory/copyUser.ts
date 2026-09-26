/**
 * Which groups a copy asks for.
 *
 * Which groups it is *offered* is the server's answer (GET /users/copy/groups):
 * the one group left out, Domain Users, is recognised by its SID, and its
 * name depends on the domain's language.
 */

/**
 * What to send as `groups`. Nothing left out means nothing is sent, and the
 * server takes all of the template's groups — which is also right when the
 * template gained a group after the dialog was opened.
 */
export function requestedGroups(groups: string[], leftOut: ReadonlySet<string>): string[] | undefined {
  if (leftOut.size === 0) return undefined
  return groups.filter((group) => !leftOut.has(group.toLowerCase()))
}
