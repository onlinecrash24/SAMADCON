/**
 * What saving one category of the advanced audit policy sends.
 *
 * Pure, so the one rule that matters can be tested: "not configured" and
 * "no auditing" are different. Not configured is an absent row — null here —
 * and leaves the subcategory to whatever else sets it; no auditing is the value
 * 0 and switches it off.
 */

function savedValue(saved: Record<string, number>, guid: string): string {
  const value = saved[guid]
  return value === undefined ? '' : String(value)
}

/** The select's value for a subcategory: '' is not configured, '0'–'3' the setting. */
export function shownValue(saved: Record<string, number>, draft: Record<string, string>, guid: string): string {
  return draft[guid] ?? savedValue(saved, guid)
}

/** The subcategories of *guids* whose draft differs from what is saved. */
export function auditChanges(
  saved: Record<string, number>,
  draft: Record<string, string>,
  guids: string[],
): Record<string, number | null> {
  const changes: Record<string, number | null> = {}
  for (const guid of guids) {
    const wanted = draft[guid]
    if (wanted === undefined || wanted === savedValue(saved, guid)) continue
    changes[guid] = wanted === '' ? null : Number(wanted)
  }
  return changes
}
