/**
 * Where in the console this tab was, so that F5 returns to it.
 *
 * Reported as a bug, and it is one: refreshing dropped whoever pressed it back
 * onto Users and Computers at the domain root, however deep in a policy tree
 * they had been. A console is not a page you re-enter from the front door.
 *
 * sessionStorage rather than the URL. The obvious alternative is a hash — it
 * would also survive F5, and it would make positions shareable, which this
 * does not. It would equally put distinguished names into the address bar, the
 * browser history and any screenshot: an organisation's OU names, and the name
 * of whichever account is selected. This console has a stance on that already
 * — the recent-servers list is kept out of the server's reach for the same
 * reason — and nobody asked for shareable links. sessionStorage is also
 * per-tab, so two tabs on two different OUs do not overwrite each other, which
 * localStorage would.
 *
 * Everything read back is treated as untrusted. It is a string a person can
 * edit, and it survives a sign-out into a different session on the same tab:
 * the same browser can be pointed at another domain controller entirely. So a
 * DN is only accepted if it belongs to the domain currently signed in to, and
 * anything unrecognised falls back to the default rather than being repaired.
 */

import { SNAPINS, type SnapinId } from '../features/console/snapins'

const STORAGE_KEY = 'samadcon.console'

// The search box is free text and lands in a query key. A stored value is not
// worth more than a sane line of it.
const MAX_SEARCH = 256

export interface ConsoleLocation {
  snapin: SnapinId
  /** The container the list is showing. */
  dn: string
  /** The object in the detail pane, still to be resolved. */
  selectedDn: string | null
  showAdvanced: boolean
  search: string
  /** The container the policy tree points at; null is "all policies". */
  gpoContainerDn: string | null
  /** The DNS zone, matched against the zone list rather than against the domain. */
  zoneDn: string | null
}

function fallback(baseDn: string): ConsoleLocation {
  return {
    snapin: 'directory',
    dn: baseDn,
    selectedDn: null,
    showAdvanced: false,
    search: '',
    gpoContainerDn: null,
    zoneDn: null,
  }
}

/** A DN is only usable if it is the domain we are in, or sits below it. */
function withinDomain(value: unknown, baseDn: string): string | null {
  if (typeof value !== 'string' || value.length < 3) return null
  const dn = value.toLowerCase()
  const base = baseDn.toLowerCase()
  return dn === base || dn.endsWith(',' + base) ? value : null
}

function knownSnapin(value: unknown): SnapinId | null {
  // Availability is checked, not just existence: a console switched off since
  // the tab was last open would land on a placeholder nobody navigated to.
  const found = SNAPINS.find((snapin) => snapin.id === value && snapin.available)
  return found ? found.id : null
}

export function readConsoleLocation(baseDn: string): ConsoleLocation {
  const defaults = fallback(baseDn)

  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return defaults

    const stored: unknown = JSON.parse(raw)
    if (typeof stored !== 'object' || stored === null) return defaults
    const value = stored as Record<string, unknown>

    return {
      snapin: knownSnapin(value.snapin) ?? defaults.snapin,
      dn: withinDomain(value.dn, baseDn) ?? defaults.dn,
      selectedDn: withinDomain(value.selectedDn, baseDn),
      showAdvanced: value.showAdvanced === true,
      search: typeof value.search === 'string' ? value.search.slice(0, MAX_SEARCH) : '',
      gpoContainerDn: withinDomain(value.gpoContainerDn, baseDn),
      // Not tested against the domain: zones can live in a forest-wide
      // partition, and the shape of that is not something to guess at here.
      // It is matched against the zone list instead, which is fetched anyway
      // once that console is opened.
      zoneDn: typeof value.zoneDn === 'string' ? value.zoneDn : null,
    }
  } catch {
    // Corrupt, or storage unavailable in a locked-down browser. Neither is a
    // reason to fail to open the console.
    return defaults
  }
}

export function writeConsoleLocation(location: ConsoleLocation): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(location))
  } catch {
    // Private browsing, or a full quota. Remembering the position is a
    // convenience and must never be the thing that breaks.
  }
}

/**
 * Forget it.
 *
 * Called on a deliberate sign-out and not when a ticket merely lapses. Signing
 * out is an ending — leaving the previous person's OU and account names in a
 * shared browser is not what that gesture means. A lapsed ticket is usually
 * the same person signing straight back in, and landing where they were is the
 * entire point of this file.
 */
export function forgetConsoleLocation(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // Nothing to do: if it cannot be removed it was never written either.
  }
}
