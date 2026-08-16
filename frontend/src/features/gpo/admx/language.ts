/**
 * Which language directory of the central store to read policy text from.
 *
 * The console's own language decides it: somebody working in German wants the
 * policy tree in German. What the store actually holds is the domain's
 * business — the server matches the exact directory if it is there, then the
 * same language in another region, then English, and reports back which one it
 * used so the editor can say so.
 *
 * Its own module because both the tree and the setting dialog ask, and they
 * import each other.
 */

const DIRECTORIES: Record<string, string> = { de: 'de-DE', en: 'en-US' }

export const FALLBACK_LANGUAGE = 'en-US'

export function admlLanguage(uiLanguage: string): string {
  return DIRECTORIES[uiLanguage] ?? FALLBACK_LANGUAGE
}
