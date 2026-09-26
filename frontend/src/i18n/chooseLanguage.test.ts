import { describe, expect, it } from 'vitest'

import { chooseLanguage } from './chooseLanguage'

describe('the language the interface starts in', () => {
  it('is the browser language when nothing is set, as before', () => {
    expect(chooseLanguage(null, null, 'de-DE')).toBe('de')
    expect(chooseLanguage(null, null, 'fr-FR')).toBe('en')
  })

  it('is the deployment default over the browser', () => {
    expect(chooseLanguage(null, 'en', 'de-DE')).toBe('en')
  })

  it('is what the person picked, over the deployment default', () => {
    expect(chooseLanguage('de', 'en', 'en-US')).toBe('de')
  })

  it('ignores a value that is not a language', () => {
    expect(chooseLanguage('xx', 'fr', 'de-AT')).toBe('de')
  })
})
