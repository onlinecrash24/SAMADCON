/**
 * The upload and download paths fail the way request() does.
 *
 * send() parsed whatever came back as JSON and let fetch's own rejection
 * through untouched. nginx answers an oversized body with an HTML page, so a
 * file just under the application's limit — whose multipart framing took the
 * request over nginx's — ended in a SyntaxError instead of "too large". Found
 * by an outside review.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, http } from './client'

function answer(status: number, body: string, type = 'text/html') {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(body, { status, headers: { 'Content-Type': type } })),
  )
}

const file = () => new File(['x'], 'Search.admx')

afterEach(() => {
  vi.unstubAllGlobals()
})

async function caught(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise
  } catch (cause) {
    return cause
  }
  throw new Error('expected a rejection')
}

describe('uploads', () => {
  it('turns nginx\'s HTML 413 into "too large", not a SyntaxError', async () => {
    answer(413, '<html><body><h1>413 Request Entity Too Large</h1></body></html>')
    const error = await caught(http.uploadFiles('/admx/store', 'files', [{ file: file(), name: 'Search.admx' }]))
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('upload_too_large')
  })

  it('names the status when something other than the application answered', async () => {
    // nginx's own 500, for a request body its spool had no room for.
    answer(500, '<html><body><h1>500 Internal Server Error</h1></body></html>')
    const error = await caught(http.upload('/admx/store', 'files', file()))
    expect((error as ApiError).code).toBe('unexpected_response')
    expect((error as ApiError).status).toBe(500)
    expect((error as ApiError).message).toContain('HTTP 500')
  })

  it('keeps the server\'s own envelope when there is one', async () => {
    answer(409, JSON.stringify({ error: { code: 'template_exists', message: 'x' } }), 'application/json')
    const error = await caught(http.upload('/admx/store', 'files', file()))
    expect((error as ApiError).code).toBe('template_exists')
  })

  it('reports a network failure as one', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const error = await caught(http.upload('/admx/store', 'files', file()))
    expect((error as ApiError).code).toBe('network_error')
  })

  it('reads a successful answer as before', async () => {
    answer(200, JSON.stringify({ added: ['Search.admx'] }), 'application/json')
    await expect(http.upload('/admx/store', 'files', file())).resolves.toEqual({ added: ['Search.admx'] })
  })
})

describe('downloads', () => {
  it('reports a network failure as one', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const error = await caught(http.download('/gpos/backup?dn=x', 'backup.zip'))
    expect((error as ApiError).code).toBe('network_error')
  })

  it('turns an HTML error page into an ApiError', async () => {
    answer(502, '<html>Bad Gateway</html>')
    const error = await caught(http.download('/gpos/backup?dn=x', 'backup.zip'))
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(502)
  })
})
