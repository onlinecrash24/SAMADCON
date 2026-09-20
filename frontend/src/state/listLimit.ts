/**
 * How many objects a container or a search may show, as this person likes it.
 *
 * ADUC has the same dial, under View → Filter Options, and for the same
 * reason: a 100 000-object OU is not something to draw in full, but 2 000 is
 * not the right ceiling for everyone either. The server enforces its own hard
 * cap (10 000) whatever is asked for here.
 *
 * localStorage, not cleared on sign-out, for the reason paneWidths gives: it
 * says nothing about any directory, it is a preference. Read back as untrusted
 * — anything but one of the offered values falls back to the default, so a
 * hand-edited "999999" cannot turn the list into a memory hog.
 */

const STORAGE_KEY = 'samadcon.listLimit'

/** The choices offered, in the order shown. The server refuses more than the last. */
export const LIST_LIMITS = [500, 1000, 2000, 5000, 10000] as const

export type ListLimit = (typeof LIST_LIMITS)[number]

/** What the list shows when nothing was ever chosen: the server's own default. */
export const DEFAULT_LIST_LIMIT: ListLimit = 2000

export function isListLimit(value: unknown): value is ListLimit {
  return typeof value === 'number' && (LIST_LIMITS as readonly number[]).includes(value)
}

export function readListLimit(): ListLimit {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_LIST_LIMIT
    const stored: unknown = JSON.parse(raw)
    return isListLimit(stored) ? stored : DEFAULT_LIST_LIMIT
  } catch {
    return DEFAULT_LIST_LIMIT
  }
}

export function writeListLimit(limit: ListLimit): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(limit))
  } catch {
    // Private mode or a full quota: the choice lasts for this page and no
    // longer, which is the most that can be done.
  }
}
