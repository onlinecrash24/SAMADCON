import { describe, expect, it } from 'vitest'

import { ApiError } from '../api/client'
import { errorHint, errorText } from './errorText'
import { de } from './messages'

describe('the words for an error', () => {
  it('say what answered, and with which status, when it was not SAMADCON', () => {
    // nginx's own 500 for a spool that ran full — the case this was written for.
    const error = new ApiError(500, { code: 'unexpected_response', message: 'The upload failed. (HTTP 500)' })
    const text = errorText(de, error)
    expect(text).toContain('HTTP 500')
    expect(text).not.toBe(error.message)
  })

  it('translate a known code', () => {
    const error = new ApiError(413, { code: 'upload_too_large', message: 'These files are too large.' })
    expect(errorText(de, error)).toBe(de['error.upload_too_large'])
  })

  it('keep the server text for a code without a translation', () => {
    const error = new ApiError(409, { code: 'something_new', message: 'Something new happened.' })
    expect(errorText(de, error)).toBe('Something new happened.')
  })
})

describe('an error with a reason', () => {
  // What the DC test met: a hand-made .admx without <resources>, refused in
  // English, and in a package of hundreds of files without saying which.
  const refused = new ApiError(422, {
    code: 'invalid_template',
    message: 'This template has no <resources> element.',
    hint: 'Every template needs one; Windows refuses the whole store without it.',
    context: { file: 'Kaputt.admx', reason: 'no_resources' },
  })

  it('is told by its reason, in the interface language, naming the file', () => {
    expect(errorText(de, refused)).toBe('Kaputt.admx hat kein <resources>-Element.')
  })

  it('gets the advice for that reason, translated', () => {
    const hint = errorHint(de, refused) ?? ''
    expect(hint).toContain('zentralen Speicher')
    expect(hint).not.toBe(refused.hint)
  })

  it('falls back to the code when the reason has no entry of its own', () => {
    const unknown = new ApiError(422, {
      code: 'invalid_template',
      message: 'x',
      context: { file: 'Neu.admx', reason: 'something_new' },
    })
    expect(errorText(de, unknown)).toBe('Die Vorlage Neu.admx ist ungültig.')
  })

  it('lists a list, and keeps the server text when a placeholder cannot be filled', () => {
    const ambiguous = new ApiError(422, {
      code: 'ambiguous_package',
      message: 'x',
      context: { folders: ['a/PolicyDefinitions', 'b/PolicyDefinitions'] },
    })
    expect(errorText(de, ambiguous)).toContain('a/PolicyDefinitions, b/PolicyDefinitions')
    const bare = new ApiError(422, { code: 'invalid_template', message: 'x' })
    expect(errorText(de, bare)).toBe('x')
  })
})

describe('a value the server sentence named', () => {
  it('reaches the German sentence through the context', () => {
    // The context the backend sends for a DNS port of 0 (test_error_context.py).
    const error = new ApiError(400, {
      code: 'number_out_of_range',
      message: 'Port must be between 1 and 65535.',
      context: { value: 0, reason: 'port', minimum: 1, maximum: 65535 },
    })
    expect(errorText(de, error)).toBe('Der Port muss zwischen 1 und 65535 liegen.')
  })

  it('names the limit that was exceeded', () => {
    const error = new ApiError(400, {
      code: 'sam_account_name_too_long',
      message: 'The logon name must not exceed 20 characters.',
      context: { limit: 20 },
    })
    expect(errorText(de, error)).toBe('Der Anmeldename darf höchstens 20 Zeichen lang sein.')
  })
})
