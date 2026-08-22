/**
 * Which overlay is on top, and who gets the Escape.
 *
 * Every dialog used to attach its own Escape listener to the document, which
 * worked exactly as long as one dialog existed. Open the policy editor, open
 * its delete confirmation on top, press Escape once — and both closed, because
 * both were listening. Nobody noticed while a second dialog was rare; with
 * windows it becomes the normal case.
 *
 * So there is one listener here, for the whole application, and it calls the
 * top of the stack. Order is registration order, which is also paint order,
 * which is also what a person means by "the one in front".
 *
 * The stack answers a second question too: only the topmost overlay should
 * tint the page behind it. Two dialogs each drawing 45% black gave 70%, and
 * the one underneath was legible on its own and unreadable in a pair.
 *
 * Overlays register from an effect and deregister from its cleanup, so
 * StrictMode's mount-unmount-mount in development is harmless by construction.
 */

let nextId = 1
const stack: { id: number; escape: () => void }[] = []
const listeners = new Set<() => void>()

function notify(): void {
  for (const listener of listeners) listener()
}

function onKeyDown(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  const top = stack[stack.length - 1]
  if (!top) return
  // Stopped so that nothing below reacts to the same press. Without this, a
  // dialog opened from inside a window would close and the window would take
  // the same Escape as its own.
  event.stopPropagation()
  top.escape()
}

/** Registers an overlay and returns the token needed to remove it again. */
export function pushOverlay(escape: () => void): number {
  if (stack.length === 0) {
    // Capture phase, so an overlay always hears Escape before whatever has
    // focus inside it can swallow the key.
    document.addEventListener('keydown', onKeyDown, true)
  }
  const id = nextId++
  stack.push({ id, escape })
  notify()
  return id
}

export function popOverlay(id: number): void {
  const index = stack.findIndex((entry) => entry.id === id)
  // Removed by identity rather than popped: an overlay does not always
  // disappear in the order it appeared.
  if (index !== -1) stack.splice(index, 1)
  if (stack.length === 0) document.removeEventListener('keydown', onKeyDown, true)
  notify()
}

export function subscribeToOverlays(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** The token of the overlay currently on top, or 0 when there is none. */
export function topOverlay(): number {
  return stack[stack.length - 1]?.id ?? 0
}
