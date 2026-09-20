/**
 * Which columns the object list shows, in which order.
 *
 * ADUC has this under View → Add/Remove Columns, and a tester who keeps
 * other attributes in the directory — or has borrowed one for another
 * service — asked for the same. Name is always first and cannot be
 * removed; it is what a row is. Everything else is chosen, ordered, and
 * remembered like the ceiling and the sort.
 *
 * The catalogue is the server's LIST_COLUMNS plus the three the row always
 * carries. A column asked for that the server does not know is refused
 * there with a code; here, one read back from storage that the catalogue
 * does not know is dropped, so a stale list after an upgrade shrinks rather
 * than breaks.
 */

import type { MessageKey } from '../i18n/messages'

const STORAGE_KEY = 'samadcon.listColumns'

export interface ColumnDef {
  id: string
  label: MessageKey
  /** Dates come from the server as ISO 8601 and are formatted here. */
  kind?: 'date'
  /** Carried by every row, not requested as an extra column. */
  builtIn?: boolean
}

export const COLUMN_CATALOGUE: ColumnDef[] = [
  { id: 'name', label: 'list.name', builtIn: true },
  { id: 'type', label: 'list.type', builtIn: true },
  { id: 'description', label: 'list.description', builtIn: true },
  { id: 'display_name', label: 'user.displayName' },
  { id: 'sam_account_name', label: 'column.samName' },
  { id: 'upn', label: 'column.upn' },
  { id: 'mail', label: 'user.mail' },
  { id: 'title', label: 'user.title' },
  { id: 'department', label: 'user.department' },
  { id: 'company', label: 'user.company' },
  { id: 'office', label: 'user.office' },
  { id: 'telephone', label: 'user.telephone' },
  { id: 'mobile', label: 'user.mobile' },
  { id: 'city', label: 'user.city' },
  { id: 'state', label: 'user.state' },
  { id: 'postal_code', label: 'user.postalCode' },
  { id: 'country', label: 'user.country' },
  { id: 'employee_id', label: 'column.employeeId' },
  { id: 'manager', label: 'user.manager' },
  { id: 'dns_host_name', label: 'computer.dnsName' },
  { id: 'operating_system', label: 'column.operatingSystem' },
  { id: 'when_created', label: 'detail.created', kind: 'date' },
  { id: 'when_changed', label: 'detail.changed', kind: 'date' },
  { id: 'last_logon', label: 'column.lastLogon', kind: 'date' },
]

const BY_ID = new Map(COLUMN_CATALOGUE.map((c) => [c.id, c]))

export const DEFAULT_COLUMNS: string[] = ['name', 'type', 'description']

export function columnDef(id: string): ColumnDef | undefined {
  return BY_ID.get(id)
}

export function isColumnId(value: unknown): value is string {
  return typeof value === 'string' && BY_ID.has(value)
}

/**
 * A list of column ids as the list will use it: known ids only, no
 * duplicates, and name first whatever was stored.
 */
export function normaliseColumns(ids: readonly unknown[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const id of ids) {
    if (!isColumnId(id) || seen.has(id) || id === 'name') continue
    seen.add(id)
    out.push(id)
  }
  return ['name', ...out]
}

/** The ids the server has to be asked for: everything a row does not carry anyway. */
export function requestedColumns(ids: readonly string[]): string[] {
  return ids.filter((id) => !BY_ID.get(id)?.builtIn)
}

export function readListColumns(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_COLUMNS
    const stored: unknown = JSON.parse(raw)
    return Array.isArray(stored) ? normaliseColumns(stored) : DEFAULT_COLUMNS
  } catch {
    return DEFAULT_COLUMNS
  }
}

export function writeListColumns(ids: readonly string[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(normaliseColumns(ids)))
  } catch {
    // Private mode or a full quota: the choice lasts for this page.
  }
}
