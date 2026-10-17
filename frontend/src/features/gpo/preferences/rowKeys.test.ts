import { describe, expect, it, vi } from 'vitest'

import { rowCommand } from './rowKeys'

const press = (key: string, shiftKey = false) => ({
  key,
  shiftKey,
  preventDefault: vi.fn(),
  stopPropagation: vi.fn(),
})

describe('the keys on a row of the list', () => {
  it('opens the item on Enter, and keeps Enter from reaching the window it opens', () => {
    // The window moves focus to its first button while the key is still
    // down; without preventDefault that button takes the Enter and the
    // window closes as it opens.
    const event = press('Enter')
    expect(rowCommand(event)).toBe('open')
    expect(event.preventDefault).toHaveBeenCalled()
    expect(event.stopPropagation).toHaveBeenCalled()
  })

  it('asks before deleting on Delete', () => {
    const event = press('Delete')
    expect(rowCommand(event)).toBe('delete')
    expect(event.preventDefault).toHaveBeenCalled()
  })

  it('opens the menu on Shift+F10 and on the context-menu key', () => {
    expect(rowCommand(press('F10', true))).toBe('menu')
    expect(rowCommand(press('ContextMenu'))).toBe('menu')
  })

  it('leaves every other key alone', () => {
    for (const event of [press('F10'), press('a'), press('Tab'), press('ArrowDown')]) {
      expect(rowCommand(event)).toBeNull()
      expect(event.preventDefault).not.toHaveBeenCalled()
      expect(event.stopPropagation).not.toHaveBeenCalled()
    }
  })
})
