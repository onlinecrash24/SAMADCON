/**
 * Which raise the dialog sends.
 *
 * The rules are samba-tool's, checked again by the server: only upwards, and
 * the forest never above the domain. Raised together, the domain goes first,
 * so "both" is always possible while the domain is below the level; the
 * forest alone only once the domain is already there.
 */

import type { FunctionalLevelState } from '../../api/types'

export type RaiseScope = 'both' | 'domain' | 'forest'

export function scopesFor(state: FunctionalLevelState, level: number): RaiseScope[] {
  if (level > state.domain_level) return ['both', 'domain']
  if (level > state.forest_level) return ['forest']
  return []
}

export function raisePayload(
  state: FunctionalLevelState,
  level: number,
  scope: RaiseScope,
): { domain_level: number | null; forest_level: number | null } | null {
  if (!scopesFor(state, level).includes(scope)) return null
  return {
    domain_level: scope === 'forest' ? null : level,
    forest_level: scope === 'domain' ? null : level,
  }
}

/** The domain's name, typed: a raise cannot be undone. */
export function confirmMatches(typed: string, domain: string): boolean {
  return typed.trim().toLowerCase() === domain.trim().toLowerCase() && domain.trim() !== ''
}
