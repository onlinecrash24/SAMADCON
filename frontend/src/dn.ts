/**
 * Facts a distinguished name states about itself.
 *
 * A DN is a path, so containment is a string question and needs no request to
 * answer. That is worth having in one place: the same test decides whether a
 * move is into its own subtree, whether a stored position still belongs to the
 * domain being signed in to, and which branches a tree opens to reveal a
 * selection. Three copies of it would eventually disagree about the comma.
 */

/**
 * The leading component of a DN, without its attribute name:
 * "CN=Anna,OU=x" → "Anna".
 *
 * The first RDN ends at the first comma that is not escaped, and a name may
 * carry escaped commas — "CN=Meyer\, Sarah,OU=x" is one object called
 * "Meyer, Sarah". A plain split on the comma gave "Meyer\" for it. RFC 4514
 * escapes are undone on the way out, so what is shown is the name.
 */
export function nameFromDn(dn: string): string {
  const first = /^(?:[^,\\]|\\.)*/.exec(dn)?.[0] ?? dn
  return first.replace(/^[A-Za-z]+=/, '').replace(/\\(.)/g, '$1')
}

/**
 * The container a DN sits in: "CN=Anna,OU=x,DC=y" → "OU=x,DC=y".
 *
 * Cut at the first unescaped comma, for the same reason as nameFromDn: the
 * object "CN=Meyer\, Sarah" lives in OU=x, not in " Sarah,OU=x".
 */
export function parentDn(dn: string): string {
  const first = /^(?:[^,\\]|\\.)*/.exec(dn)?.[0] ?? ''
  return dn.slice(first.length + 1)
}

/** Whether *dn* is *ancestor* itself, or sits anywhere below it. */
export function isAtOrBelow(dn: string | null | undefined, ancestor: string): boolean {
  if (!dn) return false
  const lower = dn.toLowerCase()
  const above = ancestor.toLowerCase()
  // The comma matters: without it "OU=Servers,DC=x" would count as below
  // "OU=Users,DC=x" for any name that merely ends the same way.
  return lower === above || lower.endsWith(',' + above)
}
