/**
 * The consoles SAMADCON offers, one tab each.
 *
 * They used to be roots of the navigation tree, MMC-style. A tester asked for
 * the opposite and was right about why: in RSAT each console is its own window
 * with its own tree — Users and Computers, Group Policy Management and the DNS
 * manager are separate programs. Siblings in one tree is the arrangement
 * nobody arrives already knowing.
 *
 * The ones that are not built yet are listed on purpose. An administrator
 * coming from RSAT looks for "DNS" and "Group Policy Management" in this tree;
 * finding them greyed out with a note is far less confusing than finding
 * nothing and wondering whether they are hidden somewhere.
 *
 * The order of this array is the order of the tabs, and it is deliberate: the
 * four that manage the domain come first, then the two that only look at it.
 * Group policy sat behind diagnosis for no better reason than the order they
 * were built in, which put the console's own reason for existing fifth.
 */

import type { MessageKey } from '../../i18n/messages'

export type SnapinId = 'directory' | 'dns' | 'sites' | 'gpo' | 'diagnostics' | 'reports'

export interface Snapin {
  id: SnapinId
  label: MessageKey
  /**
   * Which icon to draw. Its own, not one borrowed from the object set:
   * six consoles were sharing three icons, so half of them said nothing
   * about which console you were looking at.
   */
  icon: string
  available: boolean
  /** Shown when an unavailable snap-in is selected. */
  note?: MessageKey
  /**
   * Which panes this console fills.
   *
   * The list pane is not listed because every console has one — that pane is
   * the console. What differs is whether anything hangs to the left of it and
   * whether anything stands to its right, and that used to be answered by a
   * single boolean modifier that only ever asked "is this the directory?".
   * Three consoles have no tree at all, which that boolean could not say.
   */
  panes: { tree: boolean; detail: boolean }
}

export const SNAPINS: Snapin[] = [
  {
    id: 'directory',
    label: 'snapin.directory',
    icon: 'tab-directory',
    available: true,
    panes: { tree: true, detail: true },
  },
  {
    id: 'dns',
    label: 'snapin.dns',
    icon: 'tab-dns',
    available: true,
    // The zone list is the tree here.
    panes: { tree: true, detail: false },
  },
  {
    id: 'sites',
    label: 'snapin.sites',
    icon: 'tab-sites',
    available: true,
    panes: { tree: false, detail: false },
  },
  {
    id: 'gpo',
    label: 'snapin.gpo',
    icon: 'tab-gpo',
    available: true,
    // The link tree — which policies apply where.
    panes: { tree: true, detail: false },
  },
  {
    id: 'diagnostics',
    label: 'snapin.diagnostics',
    icon: 'tab-diagnostics',
    available: true,
    panes: { tree: false, detail: false },
  },

  {
    // A console of its own rather than a tab under diagnosis. It was called
    // the AI manager while it carried an optional model card at the bottom,
    // which overstated it by a wide margin: everything here is a rule in
    // core/findings.py, printed with the values it was decided from. The
    // model is gone; the name is now what the screen is.
    id: 'reports',
    label: 'snapin.reports',
    icon: 'tab-reports',
    available: true,
    panes: { tree: false, detail: false },
  },
]

/** The panes a console fills; nothing at all for an id that is not one. */
export function panesFor(id: SnapinId): { tree: boolean; detail: boolean } {
  return SNAPINS.find((snapin) => snapin.id === id)?.panes ?? { tree: false, detail: false }
}

/**
 * A console's name, for callers that need the one label rather than the list.
 *
 * The navigation pane needs it to say what it is showing: labelled "Verzeichnis"
 * while listing DNS zones, it tells a screen reader something untrue.
 */
export function snapinLabel(id: SnapinId): MessageKey {
  return SNAPINS.find((snapin) => snapin.id === id)?.label ?? 'nav.directory'
}
