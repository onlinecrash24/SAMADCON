/**
 * HTTP client.
 *
 * Two things every call depends on: the session cookie (set by the server,
 * never touched here) and the CSRF token, which the server hands out at login
 * and expects back on every state-changing request.
 */

import type { ApiErrorBody } from './types'

const BASE = '/api/v1'

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly hint?: string
  readonly detail?: string
  readonly context?: Record<string, unknown>

  constructor(status: number, body: ApiErrorBody) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.hint = body.hint
    this.detail = body.detail
    this.context = body.context
  }

  /** True when the session is gone and the UI should return to the login view. */
  get isUnauthenticated(): boolean {
    return this.status === 401
  }
}

let csrfToken: string | null = null

export function setCsrfToken(token: string | null): void {
  csrfToken = token
}

export function getCsrfToken(): string | null {
  return csrfToken
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const headers: Record<string, string> = { Accept: 'application/json' }

  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }
  if (method !== 'GET' && csrfToken) {
    headers['X-CSRF-Token'] = csrfToken
  }

  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers,
      // The session cookie is httpOnly; the browser attaches it for us.
      credentials: 'same-origin',
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    })
  } catch (cause) {
    // A network-level failure has no error envelope to unpack.
    throw new ApiError(0, {
      code: 'network_error',
      message: 'The server could not be reached.',
      detail: cause instanceof Error ? cause.message : String(cause),
    })
  }

  if (response.status === 204) {
    return undefined as T
  }

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }

  if (!response.ok) {
    const envelope = (payload as { error?: ApiErrorBody } | null)?.error
    throw new ApiError(
      response.status,
      envelope ?? {
        code: 'unexpected_response',
        message: `Request failed with status ${response.status}.`,
      },
    )
  }

  return payload as T
}

/** Encode a DN for use in a query string — they contain commas and spaces. */
export function dnParam(dn: string): string {
  return encodeURIComponent(dn)
}

/**
 * Fetch a file and hand it to the browser's downloader.
 *
 * Not a plain link: the endpoints need the session cookie *and* go through
 * the same error envelope as everything else, so a failure has to surface as
 * an ApiError rather than as a downloaded file containing JSON.
 */
async function download(path: string, fallbackName: string): Promise<void> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { Accept: '*/*' },
    credentials: 'same-origin',
  })

  if (!response.ok) {
    const text = await response.text()
    let envelope: ApiErrorBody | undefined
    try {
      envelope = (JSON.parse(text) as { error?: ApiErrorBody }).error
    } catch {
      envelope = undefined
    }
    throw new ApiError(
      response.status,
      envelope ?? { code: 'unexpected_response', message: 'The download failed.' },
    )
  }

  const disposition = response.headers.get('Content-Disposition') ?? ''
  const match = /filename="?([^";]+)"?/.exec(disposition)
  const blob = await response.blob()

  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = match?.[1] ?? fallbackName
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  // Released on the next tick; revoking immediately cancels the download in
  // some browsers.
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

/** Post a file as multipart form data. */
async function upload<T>(path: string, field: string, file: File): Promise<T> {
  const form = new FormData()
  form.append(field, file)

  const headers: Record<string, string> = { Accept: 'application/json' }
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken

  // No Content-Type here on purpose: the browser has to set it, because only
  // it knows the multipart boundary.
  const response = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers,
    credentials: 'same-origin',
    body: form,
  })

  const text = await response.text()
  const payload = text ? JSON.parse(text) : null

  if (!response.ok) {
    const envelope = (payload as { error?: ApiErrorBody } | null)?.error
    throw new ApiError(
      response.status,
      envelope ?? { code: 'unexpected_response', message: 'The upload failed.' },
    )
  }
  return payload as T
}

export const http = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  delete: <T>(path: string, body?: unknown) => request<T>(path, { method: 'DELETE', body }),
  download,
  upload,
}
