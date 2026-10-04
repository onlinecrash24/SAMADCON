/**
 * What the attribute editor lists, and what it lets through on save.
 */

import type { AttributeEntry } from '../../api/types'

/** Attributes matching the filter, set ones first, each group by name. */
export function attributeRows(
  attributes: Record<string, AttributeEntry>,
  filter: string,
): [string, AttributeEntry][] {
  const needle = filter.trim().toLowerCase()
  return Object.entries(attributes)
    .filter(([name]) => !needle || name.toLowerCase().includes(needle))
    .sort(([a, left], [b, right]) => {
      const emptyLeft = left.values.length === 0 ? 1 : 0
      const emptyRight = right.values.length === 0 ? 1 : 0
      return emptyLeft - emptyRight || a.localeCompare(b)
    })
}

/** The lines of the edit field that become values. */
export function valuesFromText(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}

/**
 * Why the edited values cannot be saved, or null if they can.
 *
 * More than one value for a single-valued attribute would be refused by the
 * DC; nothing at all for an attribute that has nothing would be a request to
 * delete what is not there.
 */
export function cannotSave(
  entry: AttributeEntry,
  values: string[],
): 'single_valued' | 'nothing' | null {
  if (entry.single_valued === true && values.length > 1) return 'single_valued'
  if (entry.values.length === 0 && values.length === 0) return 'nothing'
  return null
}
