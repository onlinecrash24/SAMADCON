/**
 * Windows that stay open, and the bar that lists them.
 *
 * Asked for by a tester, with the reason that decides the design: comparing
 * two objects means having both on screen. Every dialog in this console was a
 * single nullable owned by whichever pane happened to be showing — so only one
 * could exist, and switching console silently destroyed it.
 *
 * A window holds an identity and nothing else — a DN and which console it
 * belongs to — never a fetched object. That is the same discipline the
 * remembered console position follows, and it answers "what if someone else
 * renames or deletes it" for free: the window asks again and reports what it
 * finds.
 *
 * Windows are hidden when their console is not the active one, not unmounted.
 * Unmounting would discard a half-typed property sheet and any write already
 * in flight. The cost is that "hidden" and "closed" look the same, which is
 * why the console tab carries a count.
 *
 * Nothing here is persisted. Restoring N windows means N requests that can
 * each fail, and the stored value would be a list of distinguished names —
 * exactly what this console keeps out of the places it can be read from.
 * Positions are meaningful only against the viewport they were chosen in
 * anyway. What is remembered is one preferred size, which is most of the
 * benefit for none of the risk.
 */

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'

import type { SnapinId } from '../features/console/snapins'

export type WindowKind = 'gpo' | 'object'

export interface ConsoleWindow {
  id: string
  /** Which console owns it. Windows of other consoles are hidden, not closed. */
  snapin: SnapinId
  kind: WindowKind
  /** What makes two windows the same window. The DN. */
  key: string
  title: string
  dn: string
  x: number
  y: number
  w: number
  h: number
  z: number
  minimised: boolean
  maximised: boolean
}

export interface OpenSpec {
  snapin: SnapinId
  kind: WindowKind
  title: string
  dn: string
}

interface WindowApi {
  windows: ConsoleWindow[]
  open: (spec: OpenSpec) => void
  close: (id: string) => void
  focus: (id: string) => void
  toggleMinimised: (id: string) => void
  toggleMaximised: (id: string) => void
  move: (id: string, at: { x: number; y: number }) => void
  resize: (id: string, size: { w: number; h: number }) => void
  /** The DN changed under us — a rename or a move started from the window. */
  retarget: (id: string, dn: string, title: string) => void
}

const WindowContext = createContext<WindowApi | null>(null)

const SIZE_KEY = 'samadcon.windowSize'
const DEFAULT_SIZE = { w: 900, h: 620 }
export const MIN_SIZE = { w: 380, h: 260 }

function preferredSize(): { w: number; h: number } {
  try {
    const raw = localStorage.getItem(SIZE_KEY)
    if (!raw) return DEFAULT_SIZE
    const stored: unknown = JSON.parse(raw)
    if (typeof stored !== 'object' || stored === null) return DEFAULT_SIZE
    const { w, h } = stored as Record<string, unknown>
    if (typeof w !== 'number' || typeof h !== 'number') return DEFAULT_SIZE
    if (!Number.isFinite(w) || !Number.isFinite(h)) return DEFAULT_SIZE
    return { w: Math.max(MIN_SIZE.w, w), h: Math.max(MIN_SIZE.h, h) }
  } catch {
    return DEFAULT_SIZE
  }
}

function rememberSize(size: { w: number; h: number }): void {
  try {
    localStorage.setItem(SIZE_KEY, JSON.stringify(size))
  } catch {
    // A preference, never the thing that breaks.
  }
}

export function WindowProvider({ children }: { children: ReactNode }) {
  const [windows, setWindows] = useState<ConsoleWindow[]>([])
  // Local to the window layer's own stacking context, so it can never climb
  // into the band the dialogs use.
  const nextZ = useRef(1)

  const focus = useCallback((id: string) => {
    setWindows((current) =>
      current.map((window) =>
        window.id === id ? { ...window, z: ++nextZ.current, minimised: false } : window,
      ),
    )
  }, [])

  const open = useCallback((spec: OpenSpec) => {
    setWindows((current) => {
      // One window per object. Opening the same policy twice means the person
      // lost track of the first, so bring it forward rather than stack a
      // duplicate they will have to close twice.
      const existing = current.find((window) => window.kind === spec.kind && window.key === spec.dn)
      if (existing) {
        return current.map((window) =>
          window.id === existing.id
            ? { ...window, z: ++nextZ.current, minimised: false }
            : window,
        )
      }

      const size = preferredSize()
      // Cascaded, so a second window does not land exactly on the first.
      const step = (current.length % 8) * 24
      return [
        ...current,
        {
          id: crypto.randomUUID(),
          snapin: spec.snapin,
          kind: spec.kind,
          key: spec.dn,
          title: spec.title,
          dn: spec.dn,
          x: 60 + step,
          y: 48 + step,
          w: size.w,
          h: size.h,
          z: ++nextZ.current,
          minimised: false,
          maximised: false,
        },
      ]
    })
  }, [])

  const close = useCallback((id: string) => {
    setWindows((current) => {
      const remaining = current.filter((window) => window.id !== id)
      if (remaining.length === 0) nextZ.current = 1
      return remaining
    })
  }, [])

  const update = useCallback((id: string, change: (window: ConsoleWindow) => ConsoleWindow) => {
    setWindows((current) => current.map((window) => (window.id === id ? change(window) : window)))
  }, [])

  const api = useMemo<WindowApi>(
    () => ({
      windows,
      open,
      close,
      focus,
      toggleMinimised: (id) => update(id, (w) => ({ ...w, minimised: !w.minimised })),
      toggleMaximised: (id) => update(id, (w) => ({ ...w, maximised: !w.maximised })),
      move: (id, at) => update(id, (w) => ({ ...w, x: at.x, y: at.y })),
      resize: (id, size) => {
        update(id, (w) => ({ ...w, w: size.w, h: size.h }))
        rememberSize(size)
      },
      retarget: (id, dn, title) => update(id, (w) => ({ ...w, dn, key: dn, title })),
    }),
    [windows, open, close, focus, update],
  )

  return <WindowContext.Provider value={api}>{children}</WindowContext.Provider>
}

export function useWindows(): WindowApi {
  const api = useContext(WindowContext)
  if (!api) throw new Error('useWindows outside WindowProvider')
  return api
}
