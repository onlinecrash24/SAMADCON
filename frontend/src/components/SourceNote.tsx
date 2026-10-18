import { useI18n } from '../i18n'

/**
 * The licence this is published under, as an SPDX identifier.
 *
 * Not an i18n key on purpose: it is the same string in every language, and a
 * translated licence name is a wrong licence name.
 */
export const LICENCE = 'AGPL-3.0-or-later'

/** Where the corresponding source lives. */
export const SOURCE_URL = 'https://github.com/onlinecrash24/SAMADCON'

/** Where to support the project. The same link the README and GitHub's Sponsor button carry. */
export const COFFEE_URL = 'https://buymeacoffee.com/onlinecrash24'

/**
 * What this build is, and where it came from.
 *
 * It is in the interface rather than only in the repository because of what
 * the licence says. AGPL section 13 obliges anyone who modifies SAMADCON and
 * offers it over a network to offer its source to the people using it. A
 * console that never names its licence or its origin makes that promise
 * impossible to keep — and impossible to notice being broken.
 *
 * One component for both places it appears, the sign-in card and the console
 * header, so the two cannot drift into claiming different things.
 *
 * The version is optional because the two callers learn it differently: the
 * sign-in card already has /info in hand, the console asks for it and may not
 * have the answer yet. Missing, the line still names the licence, which is the
 * part that has to be there.
 */
export function SourceNote({ version }: { version?: string | null }) {
  const { t } = useI18n()
  return (
    <span className="source-note">
      {version && <span className="source-note__version">v{version}</span>}
      <a href={SOURCE_URL} target="_blank" rel="noreferrer" title={t('app.sourceTitle')}>
        {LICENCE}
      </a>
      {/* Drawn inline rather than loaded: the console's CSP allows images
          from itself only, and a support link is no reason to widen it. */}
      <a
        href={COFFEE_URL}
        target="_blank"
        rel="noreferrer"
        className="source-note__coffee"
        title={t('app.coffeeTitle')}
        aria-label={t('app.coffeeTitle')}
      >
        <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true" focusable="false">
          <path
            d="M4 8h12v6a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5V8Zm12 2h1.5a2.5 2.5 0 0 1 0 5H16M7 2.5c0 1 1 1.5 1 2.5S7 6.5 7 6.5M11 2.5c0 1 1 1.5 1 2.5s-1 1.5-1 1.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </a>
    </span>
  )
}
