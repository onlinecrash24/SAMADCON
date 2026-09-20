/**
 * Which column the object list is sorted by, and which way.
 *
 * The sort is done by the server, before it cuts the list at the ceiling —
 * that is the whole point. A list capped at 2 000 of 10 000 objects is only
 * "the first 2 000" if the server orders them first; two testers, comparing
 * against ADUC, called sorting by column essential, and this is the half of
 * it that has to be a request parameter rather than a click that reshuffles
 * whatever happened to load.
 *
 * Remembered like the ceiling: localStorage, not cleared on sign-out, read
 * back as untrusted.
 */

const STORAGE_KEY = 'samadcon.listSort'

export const SORT_COLUMNS = ['name', 'type', 'description'] as const

export type SortColumn = (typeof SORT_COLUMNS)[number]

export interface ListSort {
  column: SortColumn
  descending: boolean
}

export const DEFAULT_LIST_SORT: ListSort = { column: 'name', descending: false }

export function isSortColumn(value: unknown): value is SortColumn {
  return typeof value === 'string' && (SORT_COLUMNS as readonly string[]).includes(value)
}

/**
 * The sort after a click on *column*: a new column sorts ascending, the same
 * column again flips the direction — the way every column header in RSAT and
 * every file manager behaves.
 */
export function toggleSort(current: ListSort, column: SortColumn): ListSort {
  if (current.column === column) return { column, descending: !current.descending }
  return { column, descending: false }
}

export function readListSort(): ListSort {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_LIST_SORT
    const stored: unknown = JSON.parse(raw)
    if (
      typeof stored === 'object' &&
      stored !== null &&
      isSortColumn((stored as { column?: unknown }).column) &&
      typeof (stored as { descending?: unknown }).descending === 'boolean'
    ) {
      const { column, descending } = stored as ListSort
      return { column, descending }
    }
    return DEFAULT_LIST_SORT
  } catch {
    return DEFAULT_LIST_SORT
  }
}

export function writeListSort(sort: ListSort): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sort))
  } catch {
    // Private mode or a full quota: the choice lasts for this page.
  }
}
