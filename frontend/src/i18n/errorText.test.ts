import { describe, expect, it } from 'vitest'

import { ApiError } from '../api/client'
import { errorText } from './errorText'
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
