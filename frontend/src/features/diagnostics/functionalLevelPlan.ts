/**
 * Which raise command the tab shows.
 *
 * The server offers, per target level, the samba-tool commands samba-tool
 * would accept: domain and forest together or the domain alone while the
 * domain is below, the forest alone once it is not. The person picks one; a
 * pick that no longer fits the level falls back to the first offered.
 */

import type { FunctionalLevelRaise, FunctionalLevelTarget } from '../../api/types'

export type RaiseScope = FunctionalLevelRaise['scope']

export function chosenRaise(
  target: FunctionalLevelTarget,
  scope: RaiseScope,
): FunctionalLevelRaise | null {
  return target.raise.find((entry) => entry.scope === scope) ?? target.raise[0] ?? null
}
