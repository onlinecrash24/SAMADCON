/**
 * Which language the interface starts in.
 *
 * In this order, and each only when the one before says nothing:
 *
 * 1. what this person picked with the DE/EN switch — theirs, and kept;
 * 2. the deployment's default, SAMADCON_DEFAULT_LANGUAGE in the compose file;
 * 3. the browser's language, which was the only rule before there was a
 *    default to set.
 *
 * Pure, so the order is tested rather than trusted.
 */

import type { Language } from './messages'

export function isLanguage(value: unknown): value is Language {
  return value === 'de' || value === 'en'
}

export function chooseLanguage(
  picked: unknown,
  deploymentDefault: unknown,
  browserLanguage: string,
): Language {
  if (isLanguage(picked)) return picked
  if (isLanguage(deploymentDefault)) return deploymentDefault
  return browserLanguage.toLowerCase().startsWith('de') ? 'de' : 'en'
}
