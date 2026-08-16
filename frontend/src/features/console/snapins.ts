/**
 * The consoles SAMADCON offers, as MMC presents them: each snap-in is a root of
 * the navigation tree rather than a separate page.
 *
 * The ones that are not built yet are listed on purpose. An administrator
 * coming from RSAT looks for "DNS" and "Group Policy Management" in this tree;
 * finding them greyed out with a note is far less confusing than finding
 * nothing and wondering whether they are hidden somewhere.
 */

import type { MessageKey } from '../../i18n/messages'

export type SnapinId = 'directory' | 'dns' | 'sites' | 'diagnostics' | 'gpo'

export interface Snapin {
  id: SnapinId
  label: MessageKey
  /** Icon type reused from the object icon set. */
  icon: string
  available: boolean
  /** Shown when an unavailable snap-in is selected. */
  note?: MessageKey
}

export const SNAPINS: Snapin[] = [
  {
    id: 'directory',
    label: 'snapin.directory',
    icon: 'domain',
    available: true,
  },
  {
    id: 'dns',
    label: 'snapin.dns',
    icon: 'container',
    available: true,
  },
  {
    id: 'sites',
    label: 'snapin.sites',
    icon: 'container',
    available: true,
  },
  {
    id: 'diagnostics',
    label: 'snapin.diagnostics',
    icon: 'domain',
    available: true,
  },
  {
    id: 'gpo',
    label: 'snapin.gpo',
    icon: 'gpo',
    available: true,
  },
]
