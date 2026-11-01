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

import { ApiError, http, onIdpSessionExpired } from './client'

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

/**
 * An identity provider in front of SAMADCON.
 *
 * Behind a forward-auth proxy — Authelia, Authentik, oauth2-proxy — the
 * identity provider's session can end while SAMADCON's is still good. Every
 * call then gets the proxy's answer instead of the application's: measured
 * behind Nginx Proxy Manager and Authelia, a 302 to the identity provider with
 * an HTML body. fetch would follow that across origins and fail as a network
 * error, or land on the sign-in page and hand back HTML where JSON was
 * expected; a 401 from the proxy would look like SAMADCON's own and send the
 * console back to a sign-in that cannot help. Each of these is one error now,
 * and the console is told, so it can offer to reload.
 */
describe('an identity provider in front', () => {
  // A browser hands a redirect it was told not to follow back as an opaque
  // response: no status, no headers, no body. Node's fetch never does, so the
  // shape is written out.
  function opaqueRedirect() {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        type: 'opaqueredirect',
        status: 0,
        ok: false,
        redirected: false,
        headers: new Headers(),
        text: async () => '',
        blob: async () => new Blob([]),
      }) as unknown as Response),
    )
  }

  function redirect() {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('<html>Found</html>', {
        status: 302,
        headers: { 'Content-Type': 'text/html', Location: 'https://authelia.example.com/?rd=x' },
      })),
    )
  }

  async function expired(promise: Promise<unknown>) {
    const error = await caught(promise)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('idp_session_expired')
    // Not SAMADCON's session: the console must not drop to its own sign-in.
    expect((error as ApiError).isUnauthenticated).toBe(false)
  }

  it('does not let fetch follow a redirect', async () => {
    answer(200, '{}', 'application/json')
    await http.get('/auth/session')
    const init = vi.mocked(fetch).mock.calls[0]?.[1] as RequestInit
    expect(init.redirect).toBe('manual')
  })

  it("takes a redirect the browser kept back as the identity provider's", async () => {
    opaqueRedirect()
    await expired(http.get('/directory/roots'))
  })

  it('takes a plain 302 the same way', async () => {
    redirect()
    await expired(http.post('/users/unlock', { dn: 'CN=x' }))
  })

  it("takes HTML where JSON was asked for as the proxy's sign-in page", async () => {
    answer(200, '<!doctype html><title>Authelia</title>')
    await expired(http.get('/directory/roots'))
  })

  it("takes a 401 without SAMADCON's envelope as the proxy's", async () => {
    answer(401, '<html>401 Authorization Required</html>')
    await expired(http.get('/directory/roots'))
  })

  it("keeps SAMADCON's own 401 as its own", async () => {
    answer(401, JSON.stringify({ error: { code: 'session_expired', message: 'x' } }), 'application/json')
    const error = await caught(http.get('/directory/roots'))
    expect((error as ApiError).code).toBe('session_expired')
    expect((error as ApiError).isUnauthenticated).toBe(true)
  })

  it('leaves an answer without a body alone', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 204 })))
    await expect(http.delete('/users?dn=x')).resolves.toBeUndefined()
  })

  it('leaves JSON alone', async () => {
    answer(200, JSON.stringify({ ok: true }), 'application/json')
    await expect(http.get('/health')).resolves.toEqual({ ok: true })
  })

  it('catches it on an upload', async () => {
    opaqueRedirect()
    await expired(http.upload('/admx/store', 'files', file()))
  })

  it('catches it on a download', async () => {
    redirect()
    await expired(http.download('/gpos/backup?dn=x', 'backup.zip'))
  })

  it('catches a bare 401 on a download too', async () => {
    // A download is not JSON by nature, so HTML alone proves nothing there;
    // the redirect and the bare 401 still mean the proxy.
    answer(401, '<html>401</html>')
    await expired(http.download('/gpos/backup?dn=x', 'backup.zip'))
  })

  it('tells whoever listens, once per failed call, and stops when asked', async () => {
    const listener = vi.fn()
    const stop = onIdpSessionExpired(listener)
    try {
      opaqueRedirect()
      await caught(http.get('/directory/roots'))
      await caught(http.get('/directory/children?dn=x'))
      expect(listener).toHaveBeenCalledTimes(2)

      answer(401, JSON.stringify({ error: { code: 'session_expired', message: 'x' } }), 'application/json')
      await caught(http.get('/directory/roots'))
      expect(listener).toHaveBeenCalledTimes(2)
    } finally {
      stop()
    }
    opaqueRedirect()
    await caught(http.get('/directory/roots'))
    expect(listener).toHaveBeenCalledTimes(2)
  })
})
