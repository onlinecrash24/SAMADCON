/**
 * A user principal name pulled apart and put back together.
 *
 * Kept away from the component so it can be tested without a DOM, and
 * because the two halves have rules worth stating: the split is at the LAST
 * "@" (a name may not contain one, but a value read back from the directory
 * is not trusted to be well-formed), and a suffix not in the offered list is
 * kept as a choice rather than discarded — replacing it silently would change
 * an account's logon name on the next save.
 */

export interface UpnParts {
  local: string
  suffix: string
}

export function splitUpn(value: string): UpnParts {
  const at = value.lastIndexOf('@')
  return at >= 0 ? { local: value.slice(0, at), suffix: value.slice(at + 1) } : { local: value, suffix: '' }
}

/** Empty name, empty value: the property sheet reads that as "remove". */
export function composeUpn(local: string, suffix: string): string {
  return local ? `${local}@${suffix}` : ''
}

/**
 * The suffixes to offer for a value: what the forest has, plus the value's
 * own if it is not among them (compared without case — DNS names are).
 */
export function upnOptions(offered: readonly string[], current: string): string[] {
  if (!current) return [...offered]
  const known = offered.some((s) => s.toLowerCase() === current.toLowerCase())
  return known ? [...offered] : [...offered, current]
}
