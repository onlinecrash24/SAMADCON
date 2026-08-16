/**
 * Session state.
 *
 * The session cookie is httpOnly, so the browser cannot read it. What the app
 * keeps is the CSRF token and the domain information handed out at login; on a
 * page reload it asks the server who it is talking to.
 */

import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import { ApiError, setCsrfToken } from '../api/client'
import { api } from '../api/endpoints'
import type { LoginOptions, SessionInfo } from '../api/types'
import { rememberServer } from './recentServers'

interface SessionState {
  session: SessionInfo | null
  loading: boolean
  login: (username: string, password: string, options?: LoginOptions) => Promise<void>
  logout: () => Promise<void>
  /** Called when any request comes back 401 — drops local state. */
  expire: () => void
}

const SessionContext = createContext<SessionState | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const queryClient = useQueryClient()

  // Restore an existing session after a reload.
  useEffect(() => {
    let cancelled = false
    api
      .session()
      .then((info) => {
        if (cancelled) return
        setCsrfToken(info.csrf_token)
        setSession(info)
      })
      .catch(() => {
        // No session, or it expired — the login view handles it.
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(
    async (username: string, password: string, options: LoginOptions = {}) => {
      const info = await api.login(username, password, options)
      setCsrfToken(info.csrf_token)
      setSession(info)

      // Remember only what actually worked, and only when the user named a
      // server themselves — profiles and the default need no history.
      if (options.server) {
        rememberServer({
          host: options.server,
          realm: info.target?.realm ?? info.realm,
          label: info.target?.dns_domain ?? undefined,
          insecure: options.insecure ?? false,
        })
      }
    },
    [],
  )

  const expire = useCallback(() => {
    setCsrfToken(null)
    setSession(null)
    queryClient.clear()
  }, [queryClient])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } catch (error) {
      // A failed logout must not strand the user in a broken UI; the
      // server-side session expires on its own.
      if (!(error instanceof ApiError)) throw error
    }
    expire()
  }, [expire])

  const value = useMemo<SessionState>(
    () => ({ session, loading, login, logout, expire }),
    [session, loading, login, logout, expire],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionState {
  const context = useContext(SessionContext)
  if (!context) throw new Error('useSession must be used inside SessionProvider')
  return context
}
