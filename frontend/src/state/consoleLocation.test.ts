/**
 * What survives a refresh, and what is refused.
 *
 * Everything here is read back from storage a person can edit, and it survives
 * a sign-out into a session pointed at an entirely different domain
 * controller. So the interesting cases are all the ones where the stored value
 * must *not* be believed.
 */

import { beforeEach, describe, expect, it } from 'vitest'

import { forgetConsoleLocation, readConsoleLocation, writeConsoleLocation } from './consoleLocation'
import { SNAPINS } from '../features/console/snapins'

const BASE = 'DC=spam-deny,DC=local'

function fakeStorage() {
  const entries = new Map<string, string>()
  return {
    getItem: (key: string) => entries.get(key) ?? null,
    setItem: (key: string, value: string) => void entries.set(key, value),
    removeItem: (key: string) => void entries.delete(key),
    raw: entries,
  }
}

let storage: ReturnType<typeof fakeStorage>

beforeEach(() => {
  storage = fakeStorage()
  Object.defineProperty(globalThis, 'sessionStorage', { value: storage, configurable: true })
})

const full = {
  snapin: 'gpo' as const,
  dn: 'OU=Workstations,DC=spam-deny,DC=local',
  selectedDn: 'CN=Anna,OU=Benutzer,DC=spam-deny,DC=local',
  showAdvanced: true,
  search: '',
  gpoContainerDn: 'OU=Server,DC=spam-deny,DC=local',
  zoneDn: 'DC=spam-deny.local,CN=MicrosoftDNS,DC=DomainDnsZones,DC=spam-deny,DC=local',
}

describe('a position comes back', () => {
  it('opens where the console always opened when nothing is stored', () => {
    expect(readConsoleLocation(BASE)).toMatchObject({ snapin: 'directory', dn: BASE })
  })

  it('returns everything it was given', () => {
    writeConsoleLocation(full)
    expect(readConsoleLocation(BASE)).toEqual(full)
  })
})

describe('a stored DN is only believed for the domain now signed in to', () => {
  it('refuses every DN from another domain, and keeps the console', () => {
    writeConsoleLocation(full)
    const other = readConsoleLocation('DC=example,DC=test')

    expect(other.dn).toBe('DC=example,DC=test')
    expect(other.selectedDn).toBeNull()
    expect(other.gpoContainerDn).toBeNull()
    // The console is not a secret and still exists, so it survives.
    expect(other.snapin).toBe('gpo')
  })

  it('requires the comma before the base, not merely the base at the end', () => {
    // A plain endsWith would accept this: it is the base string with four
    // characters glued to the front and no separator. Malformed, which is the
    // point — the value comes out of storage a person can edit.
    const glued = `OU=x${BASE}`
    expect(glued.endsWith(BASE)).toBe(true)

    storage.raw.set('samadcon.console', JSON.stringify({ snapin: 'directory', dn: glued }))
    expect(readConsoleLocation(BASE).dn).toBe(BASE)
  })

  it('accepts a DN that really is below the domain', () => {
    storage.raw.set(
      'samadcon.console',
      JSON.stringify({ snapin: 'directory', dn: `OU=Zentral,${BASE}` }),
    )
    expect(readConsoleLocation(BASE).dn).toBe(`OU=Zentral,${BASE}`)
  })

  it('accepts the domain root itself', () => {
    writeConsoleLocation({ ...full, dn: BASE, selectedDn: null, gpoContainerDn: null })
    expect(readConsoleLocation(BASE).dn).toBe(BASE)
  })
})

describe('nonsense falls back rather than being repaired', () => {
  it('survives text that is not JSON', () => {
    storage.raw.set('samadcon.console', 'nicht mal JSON')
    expect(readConsoleLocation(BASE).snapin).toBe('directory')
  })

  it('ignores a console that does not exist', () => {
    storage.raw.set('samadcon.console', JSON.stringify({ snapin: 'gibtsnicht' }))
    expect(readConsoleLocation(BASE).snapin).toBe('directory')
  })

  it('ignores a DN that is not a string', () => {
    storage.raw.set('samadcon.console', JSON.stringify({ dn: 42 }))
    expect(readConsoleLocation(BASE).dn).toBe(BASE)
  })

  it('treats anything but true as not advanced', () => {
    storage.raw.set('samadcon.console', JSON.stringify({ showAdvanced: 'ja' }))
    expect(readConsoleLocation(BASE).showAdvanced).toBe(false)
  })

  it('caps a search term rather than passing on a wall of text', () => {
    storage.raw.set('samadcon.console', JSON.stringify({ search: 'a'.repeat(5000) }))
    expect(readConsoleLocation(BASE).search.length).toBeLessThanOrEqual(256)
  })
})

describe('a session begins and ends at Users and Computers', () => {
  it('forgets the position when told to', () => {
    // Called at both ends: signing out, and signing in. A lapsed ticket never
    // passes through signing out, so without the second call the position
    // outlived the session that chose it.
    writeConsoleLocation(full)
    forgetConsoleLocation()
    expect(readConsoleLocation(BASE).snapin).toBe('directory')
  })

  it('defaults to the directory console by name, not by position in the list', () => {
    // Reordering the tab strip must not change where a sign-in lands.
    expect(readConsoleLocation(BASE).snapin).toBe('directory')
    expect(SNAPINS[0]?.id).toBe('directory')
  })

  it('starts at the domain root, with nothing selected and no search', () => {
    expect(readConsoleLocation(BASE)).toEqual({
      snapin: 'directory',
      dn: BASE,
      selectedDn: null,
      showAdvanced: false,
      search: '',
      gpoContainerDn: null,
      zoneDn: null,
    })
  })
})

describe('storage that refuses to work must not break the console', () => {
  beforeEach(() => {
    const throwing = {
      getItem() {
        throw new Error('gesperrt')
      },
      setItem() {
        throw new Error('gesperrt')
      },
      removeItem() {
        throw new Error('gesperrt')
      },
    }
    Object.defineProperty(globalThis, 'sessionStorage', { value: throwing, configurable: true })
  })

  it('reads the defaults', () => {
    expect(readConsoleLocation(BASE).snapin).toBe('directory')
  })

  it('writes without throwing', () => {
    expect(() => writeConsoleLocation(full)).not.toThrow()
    expect(() => forgetConsoleLocation()).not.toThrow()
  })
})
