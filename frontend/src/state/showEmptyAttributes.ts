/**
 * Whether the attribute editor lists attributes that have no value.
 *
 * RSAT lists them all; most of the time they are noise — a user object may
 * have nearly 400 and has a few dozen set — so the default stays as before.
 *
 * localStorage, not cleared on sign-out, for the reason paneWidths gives: it
 * says nothing about any directory, it is a preference. Anything but a stored
 * `true` reads as off.
 */

const STORAGE_KEY = 'samadcon.showEmptyAttributes'

export function readShowEmptyAttributes(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

export function writeShowEmptyAttributes(show: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, show ? 'true' : 'false')
  } catch {
    // Private mode or a full quota: the choice lasts for this page.
  }
}
