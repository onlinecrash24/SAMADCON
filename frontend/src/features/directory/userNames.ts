/**
 * What a new user's CN — its "Full name", the Name column in the list —
 * starts as, until someone types into the field.
 *
 * One tester asked for the logon name, a later one for first and last name
 * as ADUC builds it; SAMADCON's settings in the domain choose, with ADUC's
 * rule as the default. From the name, the logon name is the fallback when
 * no name is given. Either way the field can be typed over.
 */

export type CnSource = 'name' | 'logon'

/** A CN's limit, as the dialog's field has it. */
const CN_MAX = 64

export function defaultCommonName(
  firstName: string,
  lastName: string,
  logonName: string,
  source: CnSource,
): string {
  const name = [firstName.trim(), lastName.trim()].filter(Boolean).join(' ')
  return (source === 'name' && name ? name : logonName).slice(0, CN_MAX)
}
