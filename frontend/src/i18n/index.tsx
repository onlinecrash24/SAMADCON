import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

import { ApiError } from '../api/client'
import { catalogues, de, type Language, type MessageKey } from './messages'

const STORAGE_KEY = 'samcon.language'

function detectLanguage(): Language {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === 'de' || stored === 'en') return stored
  return navigator.language.toLowerCase().startsWith('de') ? 'de' : 'en'
}

/** Keys that exist in _one/_other pairs and are used through `tn()`. */
type PluralKey =
  | 'list.count'
  | 'group.memberCount'
  | 'ou.childCount'
  | 'dns.recordCount'
  | 'sites.serverCount'

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

    const te: I18n['te'] = (error) => {
      if (error instanceof ApiError) {
        const key = `error.${error.code}` as MessageKey
        const translated = catalogue[key] ?? de[key]
        // An unmapped code still has a usable English message from the server.
        return translated ?? error.message
      }
      if (error instanceof Error) return error.message
      return String(error)
    }

    const th: I18n['th'] = (error) => {
      if (!(error instanceof ApiError)) return undefined
      const key = `error.${error.code}.hint` as MessageKey
      // An unmapped code keeps the server's English advice, which beats none.
      return catalogue[key] ?? de[key] ?? error.hint
    }

    return { language, setLanguage, t, tn, te, th }
  }, [language, setLanguage])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18n {
  const context = useContext(I18nContext)
  if (!context) throw new Error('useI18n must be used inside I18nProvider')
  return context
}
