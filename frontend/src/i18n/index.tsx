import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { api } from '../api/endpoints'
import { chooseLanguage, isLanguage } from './chooseLanguage'
import { errorHint, errorText } from './errorText'
import { catalogues, de, type Language, type MessageKey } from './messages'

/** What this person picked with the DE/EN switch. */
const STORAGE_KEY = 'samadcon.language'
/**
 * The deployment's default as last seen. Not a choice, and never written by
 * the switch: kept only so the page starts in it instead of flashing the
 * browser's language until /info has answered.
 */
const DEFAULT_KEY = 'samadcon.defaultLanguage'

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function detectLanguage(): Language {
  return chooseLanguage(read(STORAGE_KEY), read(DEFAULT_KEY), navigator.language)
}

/** Keys that exist in _one/_other pairs and are used through `tn()`. */
type PluralKey =
  | 'list.count'
  | 'group.memberCount'
  | 'ou.childCount'
  | 'dns.recordCount'
  | 'sites.serverCount'
  | 'sheet.pending'

interface I18n {
  language: Language
  setLanguage: (language: Language) => void
  t: (key: MessageKey, params?: Record<string, string | number>) => string
  /** Plural-aware counterpart to `t`, picking the _one or _other form. */
  tn: (key: PluralKey, count: number, params?: Record<string, string | number>) => string
  /** Translate an API error by its stable code, falling back to the server text. */
  te: (error: unknown) => string
  /**
   * The advice that goes with an error, translated where we have it.
   *
   * The server writes its hints in English. Showing one verbatim under a
   * translated message reads like a half-finished console — and the hint is
   * the part that says what to do about it, so it is the worse half to leave
   * in the wrong language.
   */
  th: (error: unknown) => string | undefined
}

const I18nContext = createContext<I18n | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(detectLanguage)

  // The deployment's default, from the server. Applied only while this
  // person has picked nothing; remembered for the next start either way.
  useEffect(() => {
    let current = true
    api
      .info()
      .then((info) => {
        if (!current) return
        const fallback = isLanguage(info.default_language) ? info.default_language : null
        try {
          if (fallback) localStorage.setItem(DEFAULT_KEY, fallback)
          else localStorage.removeItem(DEFAULT_KEY)
        } catch {
          // No storage: the default still applies to this page.
        }
        if (isLanguage(read(STORAGE_KEY))) return
        const next = chooseLanguage(null, fallback, navigator.language)
        document.documentElement.lang = next
        setLanguageState(next)
      })
      .catch(() => {
        // Unreachable server: the sign-in page says so; the language stays.
      })
    return () => {
      current = false
    }
  }, [])

  const setLanguage = useCallback((next: Language) => {
    localStorage.setItem(STORAGE_KEY, next)
    document.documentElement.lang = next
    setLanguageState(next)
  }, [])

  const value = useMemo<I18n>(() => {
    const catalogue = catalogues[language] ?? de

    const t: I18n['t'] = (key, params) => {
      const template = catalogue[key] ?? de[key] ?? key
      if (!params) return template
      return Object.entries(params).reduce(
        (text, [name, replacement]) => text.replaceAll(`{${name}}`, String(replacement)),
        template as string,
      )
    }

    // German and English share the same rule (one vs. everything else), so a
    // full CLDR plural implementation would be dead weight here. A language
    // with more forms would need one.
    const tn: I18n['tn'] = (key, count, params) =>
      t(`${key}_${count === 1 ? 'one' : 'other'}` as MessageKey, { count, ...params })

    const te: I18n['te'] = (error) => errorText({ ...de, ...catalogue }, error)

    // An unmapped code keeps the server's English advice, which beats none.
    const th: I18n['th'] = (error) => errorHint({ ...de, ...catalogue }, error)

    return { language, setLanguage, t, tn, te, th }
  }, [language, setLanguage])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18n {
  const context = useContext(I18nContext)
  if (!context) throw new Error('useI18n must be used inside I18nProvider')
  return context
}
