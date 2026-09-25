/**
 * What a template import sends.
 *
 * Microsoft's package carries 22 languages and 97 MB; one upload stops at 64.
 * An MSI or a ZIP is narrowed down on the server, which can open them. A
 * folder picked in the browser arrives file by file, and those are narrowed
 * down here, before anything is sent — about 12 MB for two languages.
 */

/** The language directories in Microsoft's Windows 11 package (25H2, v2.0). */
export const MICROSOFT_LANGUAGES = [
  'cs-CZ',
  'da-DK',
  'de-DE',
  'el-GR',
  'en-US',
  'es-ES',
  'fi-FI',
  'fr-FR',
  'hu-HU',
  'it-IT',
  'ja-JP',
  'ko-KR',
  'nb-NO',
  'nl-NL',
  'pl-PL',
  'pt-BR',
  'pt-PT',
  'ru-RU',
  'sv-SE',
  'tr-TR',
  'zh-CN',
  'zh-TW',
] as const

/**
 * German for the text, English because it is what a template falls back to
 * when its translation is missing — SecureBoot.admx has no German one.
 */
export const DEFAULT_LANGUAGES = ['de-DE', 'en-US']

/** The same ceiling nginx and the API enforce. */
export const MAX_UPLOAD_BYTES = 64 * 1024 * 1024

export interface PickedFile {
  /** The path the server should see, e.g. `PolicyDefinitions/de-de/x.adml`. */
  path: string
  size: number
}

/**
 * The files of a picked folder worth sending.
 *
 * Every `.admx` goes; an `.adml` goes when the directory it sits in is one of
 * the chosen languages, however the package spells it (Microsoft writes
 * `de-de`). Nothing else goes. Which directory holds the templates is not
 * decided here — the server does that, by the same rule for every route.
 */
export function folderFilesToSend<T extends PickedFile>(
  files: T[],
  languages: string[],
): { send: T[]; left: number; bytes: number } {
  const wanted = new Set(languages.map((item) => item.toLowerCase()))
  const send: T[] = []
  let left = 0

  for (const file of files) {
    const parts = file.path.replaceAll('\\', '/').split('/')
    const name = parts[parts.length - 1]!.toLowerCase()
    const directory = parts.length >= 2 ? parts[parts.length - 2]!.toLowerCase() : ''

    if (name.endsWith('.admx') || (name.endsWith('.adml') && wanted.has(directory))) {
      send.push(file)
    } else {
      left += 1
    }
  }

  return { send, left, bytes: send.reduce((total, file) => total + file.size, 0) }
}

/** Sizes a reader can weigh, without pretending to more precision than matters. */
export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}
