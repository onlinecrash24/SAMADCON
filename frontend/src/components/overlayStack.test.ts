/**
 * Which overlay gets the Escape.
 *
 * The bug this replaces: every dialog listened on the document, so opening a
 * confirmation on top of the policy editor and pressing Escape once closed
 * both. That was invisible while a second dialog was rare; with windows it is
 * the normal case.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { popOverlay, pushOverlay, subscribeToOverlays, topOverlay } from './overlayStack'

let handlers: Set<(event: { key: string; stopPropagation: () => void }) => void>
let opened: number[]

/** Presses Escape, and reports whether the press was stopped from spreading. */
function escape(): boolean {
  let stopped = false
  for (const handler of handlers) handler({ key: 'Escape', stopPropagation: () => (stopped = true) })
  return stopped
}

beforeEach(() => {
  handlers = new Set()
  opened = []
  Object.defineProperty(globalThis, 'document', {
    configurable: true,
    value: {
      addEventListener: (type: string, fn: never) => {
        if (type === 'keydown') handlers.add(fn)
      },
      removeEventListener: (type: string, fn: never) => {
        if (type === 'keydown') handlers.delete(fn)
      },
    },
  })
  // Whatever the previous test left behind: the stack is module state.
  while (topOverlay() !== 0) popOverlay(topOverlay())
})

describe('one press reaches one overlay', () => {
  it('closes only the upper of two', () => {
    const closed: string[] = []
    const lower = pushOverlay(() => closed.push('lower'))
    const upper = pushOverlay(() => closed.push('upper'))
    opened.push(lower, upper)

    expect(escape()).toBe(true)
    expect(closed).toEqual(['upper'])
  })

  it('reaches the one underneath once the upper is gone', () => {
    const closed: string[] = []
    const lower = pushOverlay(() => closed.push('lower'))
    const upper = pushOverlay(() => closed.push('upper'))

    popOverlay(upper)
    escape()
    expect(closed).toEqual(['lower'])
    popOverlay(lower)
  })

  it('stops the press from spreading, so nothing below takes it as well', () => {
    const token = pushOverlay(() => {})
    expect(escape()).toBe(true)
    popOverlay(token)
  })
})

describe('overlays leave in any order', () => {
  it('removes by identity rather than popping', () => {
    const closed: string[] = []
    const first = pushOverlay(() => closed.push('first'))
    const second = pushOverlay(() => closed.push('second'))

    // The lower one closes first, which happens: a dialog behind a menu.
    popOverlay(first)
    expect(topOverlay()).toBe(second)

    escape()
    expect(closed).toEqual(['second'])
    popOverlay(second)
  })

  it('shrugs at being removed twice', () => {
    // StrictMode mounts, unmounts and mounts again in development.
    const token = pushOverlay(() => {})
    popOverlay(token)
    expect(() => popOverlay(token)).not.toThrow()
    expect(topOverlay()).toBe(0)
  })
})

describe('the listener', () => {
  it('is attached once however many overlays there are', () => {
    const a = pushOverlay(() => {})
    expect(handlers.size).toBe(1)
    const b = pushOverlay(() => {})
    expect(handlers.size).toBe(1)
    popOverlay(a)
    popOverlay(b)
  })

  it('is gone once the last overlay is', () => {
    const token = pushOverlay(() => {})
    popOverlay(token)
    expect(handlers.size).toBe(0)
  })
})

describe('subscribers', () => {
  it('hear about every change', () => {
    const heard = vi.fn()
    const stop = subscribeToOverlays(heard)

    const token = pushOverlay(() => {})
    popOverlay(token)

    expect(heard).toHaveBeenCalledTimes(2)
    stop()
  })

  it('stop hearing once they unsubscribe', () => {
    const heard = vi.fn()
    subscribeToOverlays(heard)()

    const token = pushOverlay(() => {})
    popOverlay(token)
    expect(heard).not.toHaveBeenCalled()
  })
})
