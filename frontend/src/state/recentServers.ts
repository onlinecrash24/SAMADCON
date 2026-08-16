/**
 * Servers this browser has signed in to before.
 *
 * Kept in localStorage rather than on the server: it is a per-person
 * convenience, and a list of an organisation's domain controllers is not
 * something an unauthenticated endpoint should hand out.
 *
 * No credentials are stored — only the address, the realm it turned out to
 * belong to, and whether the certificate check had to be waived.
 */

const STORAGE_KEY = 'samcon.recentServers'
const MAX_ENTRIES = 5

export interface RecentServer {
  host: string
  realm: string
  label?: string
  insecure: boolean
  lastUsed: number
}

function isRecentServer(value: unknown): value is RecentServer {
  if (typeof value !== 'object' || value === null) return false
  const entry = value as Record<string, unknown>
  return typeof entry.host === 'string' && typeof entry.realm === 'string'
}

export function loadRecentServers(): RecentServer[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter(isRecentServer)
      .sort((a, b) => (b.lastUsed ?? 0) - (a.lastUsed ?? 0))
      .slice(0, MAX_ENTRIES)
  } catch {
    // Corrupt or unavailable storage must not break the sign-in form.
    return []
  }
}

export function rememberServer(entry: Omit<RecentServer, 'lastUsed'>): void {
  try {
    const others = loadRecentServers().filter(
      (item) => item.host.toLowerCase() !== entry.host.toLowerCase(),
    )
    const updated = [{ ...entry, lastUsed: Date.now() }, ...others].slice(0, MAX_ENTRIES)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updated))
  } catch {
    // Private browsing or a full quota — not worth surfacing.
  }
}

export function forgetServer(host: string): void {
  try {
    const remaining = loadRecentServers().filter(
      (item) => item.host.toLowerCase() !== host.toLowerCase(),
    )
    localStorage.setItem(STORAGE_KEY, JSON.stringify(remaining))
  } catch {
    /* ignored */
  }
}
