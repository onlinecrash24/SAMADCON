import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { ApiError } from './api/client'
import { App } from './App'
import { IdpExpiredNotice } from './components/IdpExpiredNotice'
import { I18nProvider } from './i18n'
import { SessionProvider } from './state/session'
import './styles.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Directory data is shared state that other administrators change too;
      // refetching on focus keeps a stale list from misleading anyone.
      refetchOnWindowFocus: true,
      staleTime: 10_000,
      retry: (failureCount, error) => {
        // Retrying a 401/403/404 only delays the error the user needs to see.
        if (error instanceof ApiError && error.status > 0 && error.status < 500) return false
        // Nor does asking the proxy in front again: its answer is status 0
        // for a redirect the browser kept back, and it will not change.
        if (error instanceof ApiError && error.code === 'idp_session_expired') return false
        return failureCount < 2
      },
    },
    mutations: { retry: false },
  },
})

const container = document.getElementById('root')
if (!container) throw new Error('#root is missing from index.html')

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <SessionProvider>
          <App />
        </SessionProvider>
        <IdpExpiredNotice />
      </I18nProvider>
    </QueryClientProvider>
  </StrictMode>,
)
