/**
 * "User must change password at next logon" and "Password never expires",
 * which exclude each other — in ADUC, ticking one clears the other.
 *
 * SAMADCON had them as two unrelated boxes, and a tester saved both; a copy
 * of a template whose password never expires came out the same way. One
 * rule, used by the Account tab, the copy dialog and the password reset.
 */

export interface PasswordOptions {
  mustChange: boolean
  neverExpires: boolean
}

export type PasswordOption = keyof PasswordOptions

/**
 * The options after one box is ticked or cleared, and which other box that
 * cleared — so the screen can say why it moved, as ADUC does.
 */
export function choosePasswordOption(
  current: PasswordOptions,
  which: PasswordOption,
  value: boolean,
): { next: PasswordOptions; cleared: PasswordOption | null } {
  const other: PasswordOption = which === 'mustChange' ? 'neverExpires' : 'mustChange'
  const clears = value && current[other]
  return {
    next: { ...current, [which]: value, ...(clears ? { [other]: false } : {}) },
    cleared: clears ? other : null,
  }
}

/** An account saved with both before this rule existed. */
export function bothSet(options: PasswordOptions): boolean {
  return options.mustChange && options.neverExpires
}
