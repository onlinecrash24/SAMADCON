/**
 * What a key does on a row of the preference list, as GPMC has it: Enter
 * opens the item, Delete asks to remove it, Shift+F10 or the context-menu
 * key opens the menu.
 *
 * A key that does something is consumed. For Enter this is not tidiness:
 * the window it opens moves focus to its first button while the key is
 * still down, and an Enter left to run on would press that button — the
 * window closed in the same keystroke that opened it.
 */

export type RowCommand = 'open' | 'delete' | 'menu'

export interface RowKeyEvent {
  key: string
  shiftKey: boolean
  preventDefault(): void
  stopPropagation(): void
}

export function rowCommand(event: RowKeyEvent): RowCommand | null {
  let command: RowCommand | null = null
  if (event.key === 'Enter') command = 'open'
  else if (event.key === 'Delete') command = 'delete'
  else if ((event.shiftKey && event.key === 'F10') || event.key === 'ContextMenu') command = 'menu'
  if (command) {
    event.preventDefault()
    event.stopPropagation()
  }
  return command
}
