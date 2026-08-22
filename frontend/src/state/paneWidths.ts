/**
 * How wide each console's panes are, as this person likes them.
 *
 * localStorage, and deliberately not cleared on sign-out — unlike
 * [consoleLocation], which holds distinguished names and is therefore
 * sessionStorage and wiped when someone signs out. A column width says nothing
 * about a directory. It is a preference, and it belongs beside the language
 * choice and the recent-server list, which are kept the same way.
 *
 * Per console rather than one width for all of them. The DNS zone list is a
 * flat column of short names and wants little; the policy tree draws indented
 * policies with badges under every container and wants a lot. RSAT's separate
 * windows each remember their own, for the same reason.
 *
 * Everything read back is treated as untrusted: it is a string a person can
 * edit, and a nonsensical width would wedge the layout with no way back except
 * developer tools. Values are clamped rather than repaired creatively, and
 * anything unrecognisable falls back to "no preference" — which means the
 * stylesheet's own default, written down in exactly one place.
 */

import type { SnapinId } from '../features/console/snapins'

const STORAGE_KEY = 'samadcon.panes'

/** Which boundary a width belongs to. */
export type Boundary = 'tree' | 'detail'

/**
 * The bounds a drag may not leave.
 *
 * The same numbers guard the drag and the read, on purpose: a value that could
 * be stored but not dragged to would be unreachable and unremovable.
 */
export const LIMITS: Record<Boundary, { min: number; max: number }> = {
  tree: { min: 180, max: 480 },
  detail: { min: 320, max: 760 },
}

/** The list pane never goes below this, whatever the panes beside it want. */
export const LIST_MIN = 340

export type PaneWidths = Partial<Record<Boundary, number>>

export function clampWidth(boundary: Boundary, px: number): number {
  const { min, max } = LIMITS[boundary]
  return Math.min(max, Math.max(min, Math.round(px)))
}

function validWidth(boundary: Boundary, value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
  return clampWidth(boundary, value)
}

export function readPaneWidths(): Partial<Record<SnapinId, PaneWidths>> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}

    const stored: unknown = JSON.parse(raw)
    if (typeof stored !== 'object' || stored === null) return {}

    const result: Partial<Record<SnapinId, PaneWidths>> = {}
    for (const [id, value] of Object.entries(stored as Record<string, unknown>)) {
      if (typeof value !== 'object' || value === null) continue
      const widths = value as Record<string, unknown>
      const tree = validWidth('tree', widths.tree)
      const detail = validWidth('detail', widths.detail)
      // The console id is not checked against the list. An id that no longer
      // exists simply never gets looked up, and dropping it here would delete
      // the width of a console that is only temporarily switched off.
      if (tree !== undefined || detail !== undefined) {
        result[id as SnapinId] = { ...(tree !== undefined && { tree }), ...(detail !== undefined && { detail }) }
      }
    }
    return result
  } catch {
    // Corrupt, or storage unavailable in a locked-down browser. Neither is a
    // reason to fail to draw the console.
    return {}
  }
}

export function writePaneWidths(widths: Partial<Record<SnapinId, PaneWidths>>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(widths))
  } catch {
    // Private browsing, or a full quota. Remembering a width is a convenience
    // and must never be the thing that breaks.
  }
}
