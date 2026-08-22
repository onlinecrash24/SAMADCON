/**
 * Facts a distinguished name states about itself.
 *
 * A DN is a path, so containment is a string question and needs no request to
 * answer. That is worth having in one place: the same test decides whether a
 * move is into its own subtree, whether a stored position still belongs to the
 * domain being signed in to, and which branches a tree opens to reveal a
 * selection. Three copies of it would eventually disagree about the comma.
 */

/** Whether *dn* is *ancestor* itself, or sits anywhere below it. */
export function isAtOrBelow(dn: string | null | undefined, ancestor: string): boolean {
  if (!dn) return false
  const lower = dn.toLowerCase()
  const above = ancestor.toLowerCase()
  // The comma matters: without it "OU=Servers,DC=x" would count as below
  // "OU=Users,DC=x" for any name that merely ends the same way.
  return lower === above || lower.endsWith(',' + above)
}
