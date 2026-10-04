/**
 * The two branches GPMC files preferences under, and which types go where.
 *
 * GPMC shows Preferences ("Einstellungen") as Windows Settings and Control
 * Panel Settings. The editor had one tab for both, named after the parent;
 * named "Windows-Einstellungen" instead, it would have claimed printers,
 * local groups, services and tasks for the wrong branch — and been confused
 * with Policies › Windows Settings, which holds scripts, security settings and
 * folder redirection.
 *
 * A Record over every type id, so a type added to PreferenceTypeId without a
 * branch does not compile.
 */

import type { PreferenceTypeId } from '../../../api/types'

export type PreferenceArea = 'windows' | 'controlPanel'

const AREA_OF: Record<PreferenceTypeId, PreferenceArea> = {
  drives: 'windows',
  environment: 'windows',
  files: 'windows',
  folders: 'windows',
  registry: 'windows',
  shortcuts: 'windows',
  printers: 'controlPanel',
  groups: 'controlPanel',
  services: 'controlPanel',
  tasks: 'controlPanel',
}

/** The type a branch opens on: the one most often wanted there. */
export const FIRST_TYPE: Record<PreferenceArea, PreferenceTypeId> = {
  windows: 'registry',
  controlPanel: 'groups',
}

/**
 * The branch a type belongs to. A type the server offers that this build does
 * not know yet is shown under Windows Settings rather than not at all.
 */
export function areaOf(type: string): PreferenceArea {
  return (AREA_OF as Record<string, PreferenceArea>)[type] ?? 'windows'
}

/** The catalogue's types for one branch, in the catalogue's order. */
export function typesIn<T extends { id: string }>(area: PreferenceArea, types: T[]): T[] {
  return types.filter((type) => areaOf(type.id) === area)
}
