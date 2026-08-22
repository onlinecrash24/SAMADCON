/**
 * Stored pane widths, and why they are clamped rather than corrected.
 *
 * A hand-edited width is the one stored value that can wedge the layout with
 * no way back except developer tools, so nothing here is trusted and nothing
 * is creatively repaired.
 */

import { beforeEach, describe, expect, it } from 'vitest'

import { clampWidth, LIMITS, readPaneWidths, writePaneWidths } from './paneWidths'

let entries: Map<string, string>

beforeEach(() => {
  entries = new Map()
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => entries.get(key) ?? null,
      setItem: (key: string, value: string) => void entries.set(key, value),
      removeItem: (key: string) => void entries.delete(key),
    },
  })
})

describe('widths are remembered per console', () => {
  it('starts with no preference at all', () => {
    expect(readPaneWidths()).toEqual({})
  })

  it('keeps them apart', () => {
    // The zone list is a flat column of short names; the policy tree draws
    // indented policies with badges. They do not want the same width.
    writePaneWidths({ dns: { tree: 220 }, gpo: { tree: 360 } })
    expect(readPaneWidths()).toEqual({ dns: { tree: 220 }, gpo: { tree: 360 } })
  })

  it('keeps a console it does not currently know about', () => {
    // Dropping it would delete the width of a console that is only
    // temporarily switched off.
    entries.set('samadcon.panes', JSON.stringify({ kuenftig: { tree: 250 } }))
    expect(readPaneWidths()).toEqual({ kuenftig: { tree: 250 } })
  })
})

describe('an impossible width is clamped, not obeyed', () => {
  it('pulls an absurd one back to the limit', () => {
    entries.set('samadcon.panes', JSON.stringify({ directory: { tree: 9999, detail: 1 } }))
    expect(readPaneWidths()).toEqual({
      directory: { tree: LIMITS.tree.max, detail: LIMITS.detail.min },
    })
  })

  it('pulls a negative one back too', () => {
    entries.set('samadcon.panes', JSON.stringify({ directory: { tree: -50 } }))
    expect(readPaneWidths()).toEqual({ directory: { tree: LIMITS.tree.min } })
  })

  it('uses the same bounds for the drag and the read', () => {
    // A value that could be stored but never dragged to would be unreachable
    // and unremovable.
    expect(clampWidth('tree', 10)).toBe(LIMITS.tree.min)
    expect(clampWidth('detail', 5000)).toBe(LIMITS.detail.max)
    expect(clampWidth('tree', 233.7)).toBe(234)
  })
})

describe('nonsense is dropped', () => {
  it('drops a width that is not a number', () => {
    entries.set('samadcon.panes', JSON.stringify({ directory: { tree: 'breit' } }))
    expect(readPaneWidths()).toEqual({})
  })

  it('drops one that is not finite', () => {
    entries.set('samadcon.panes', JSON.stringify({ directory: { tree: 1e400 } }))
    expect(readPaneWidths()).toEqual({})
  })

  it('survives text that is not JSON', () => {
    entries.set('samadcon.panes', 'kein JSON')
    expect(readPaneWidths()).toEqual({})
  })

  it('survives an array where an object belongs', () => {
    entries.set('samadcon.panes', JSON.stringify([1, 2, 3]))
    expect(readPaneWidths()).toEqual({})
  })
})

describe('storage that refuses to work', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: {
        getItem() {
          throw new Error('gesperrt')
        },
        setItem() {
          throw new Error('gesperrt')
        },
        removeItem() {
          throw new Error('gesperrt')
        },
      },
    })
  })

  it('reads as no preference', () => {
    expect(readPaneWidths()).toEqual({})
  })

  it('writes without throwing', () => {
    expect(() => writePaneWidths({ directory: { tree: 300 } })).not.toThrow()
  })
})
