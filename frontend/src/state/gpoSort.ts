/**
 * How the policy list is sorted, chosen by clicking a column header.
 *
 * Two views, remembered separately, because they answer different questions.
 * All policies: which ones exist — by name unless asked otherwise, as the
 * server delivers them. The policies linked to a container: what applies
 * there — by link order unless asked otherwise, because that order decides
 * which policy wins and GPMC shows it first. A tester read the link order
 * as "sorted by date": new links are usually appended, so it often looks
 * like one.
 *
 * Sorted here rather than by the server: the list is small and already
 * complete. Remembered like listSort: localStorage, read back as untrusted.
 */

const STORAGE_KEY = 'samadcon.gpoSort'

export type GpoView = 'all' | 'linked'
export type GpoSortColumn = 'order' | 'name' | 'changed'

export interface GpoSort {
  column: GpoSortColumn
  descending: boolean
}

export const DEFAULT_GPO_SORT: Record<GpoView, GpoSort> = {
  all: { column: 'name', descending: false },
  linked: { column: 'order', descending: false },
}

/** A policy with its link order in the container shown; null for all policies. */
export interface GpoRow<T> {
  gpo: T
  order: number | null
}

interface Sortable {
  display_name: string | null
  guid: string
  changed?: string | null
}

const COLUMNS: Record<GpoView, readonly GpoSortColumn[]> = {
  all: ['name', 'changed'],
  linked: ['order', 'name', 'changed'],
}

const collator = new Intl.Collator(undefined, { sensitivity: 'base', numeric: true })

const label = (gpo: Sortable) => gpo.display_name ?? gpo.guid

function timeOf(value: string | null | undefined): number | null {
  if (!value) return null
  const time = Date.parse(value)
  return Number.isNaN(time) ? null : time
}

/** The rows in the chosen order; a copy, the input is left as it was. */
export function sortGpos<T extends Sortable>(rows: GpoRow<T>[], sort: GpoSort): GpoRow<T>[] {
  const direction = sort.descending ? -1 : 1
  const byName = (a: GpoRow<T>, b: GpoRow<T>) =>
    collator.compare(label(a.gpo), label(b.gpo)) || a.gpo.guid.localeCompare(b.gpo.guid)

  // Rows without the value go last whichever way the column is sorted: a
  // policy with no date is not the oldest one.
  const byValue = (value: (row: GpoRow<T>) => number | null) => (a: GpoRow<T>, b: GpoRow<T>) => {
    const left = value(a)
    const right = value(b)
    if (left === null && right === null) return byName(a, b)
    if (left === null) return 1
    if (right === null) return -1
    return (left - right) * direction || byName(a, b)
  }

  const compare =
    sort.column === 'name'
      ? (a: GpoRow<T>, b: GpoRow<T>) => byName(a, b) * direction
      : sort.column === 'changed'
        ? byValue((row) => timeOf(row.gpo.changed))
        : byValue((row) => row.order)

  return [...rows].sort(compare)
}

/** A new column sorts ascending; the same column again flips the direction. */
export function toggleGpoSort(current: GpoSort, column: GpoSortColumn): GpoSort {
  if (current.column === column) return { column, descending: !current.descending }
  return { column, descending: false }
}

function readAll(): Partial<Record<GpoView, unknown>> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const stored: unknown = JSON.parse(raw)
    return typeof stored === 'object' && stored !== null
      ? (stored as Partial<Record<GpoView, unknown>>)
      : {}
  } catch {
    return {}
  }
}

export function readGpoSort(view: GpoView): GpoSort {
  const stored = readAll()[view] as { column?: unknown; descending?: unknown } | undefined
  if (
    stored &&
    typeof stored.descending === 'boolean' &&
    (COLUMNS[view] as readonly unknown[]).includes(stored.column)
  ) {
    return { column: stored.column as GpoSortColumn, descending: stored.descending }
  }
  return DEFAULT_GPO_SORT[view]
}

export function writeGpoSort(view: GpoView, sort: GpoSort): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...readAll(), [view]: sort }))
  } catch {
    // Private mode or a full quota: the choice lasts for this page.
  }
}
