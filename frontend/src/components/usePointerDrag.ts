/**
 * Dragging something with a pointer, without leaking listeners.
 *
 * Pointer capture rather than listeners on the document: once the element has
 * captured the pointer, every move and release is delivered back to that
 * element, so the handlers are ordinary React props and there is nothing to
 * remove if the component unmounts mid-drag. The alternative — adding to
 * `document` on mousedown — is the shape that leaves a stuck listener behind
 * whenever the release lands somewhere unexpected.
 *
 * Escape cancels, and cancelling is a real state: the caller is told, so it can
 * put back whatever it was changing rather than keep the half-dragged value.
 * That one listener does have to be on the document, because a captured
 * pointer is not focus and key presses go elsewhere.
 *
 * Everything is idempotent. StrictMode runs effects twice in development, and
 * a drag that only half tears down leaves the resize cursor stuck over the
 * whole page.
 */

import { useRef, type PointerEvent as ReactPointerEvent } from 'react'

export interface PointerDrag {
  onPointerDown: (event: ReactPointerEvent<HTMLElement>) => void
  onPointerMove: (event: ReactPointerEvent<HTMLElement>) => void
  onPointerUp: (event: ReactPointerEvent<HTMLElement>) => void
  onPointerCancel: (event: ReactPointerEvent<HTMLElement>) => void
  onLostPointerCapture: (event: ReactPointerEvent<HTMLElement>) => void
}

export function usePointerDrag({
  onStart,
  onMove,
  onEnd,
}: {
  /** Return false to refuse the drag — a secondary button, say. */
  onStart: (event: ReactPointerEvent<HTMLElement>) => boolean
  onMove: (event: ReactPointerEvent<HTMLElement>) => void
  onEnd: (cancelled: boolean) => void
}): PointerDrag {
  const active = useRef(false)
  const pointerId = useRef<number | null>(null)
  const element = useRef<HTMLElement | null>(null)

  // One function object for the lifetime of the hook, wrapping a ref that the
  // current render fills in. Registering an inline arrow would mean removing a
  // different object than was added, every time the parent re-rendered
  // mid-drag — which it does, on every pointer move.
  const cancel = useRef<() => void>(() => {})
  const onKey = useRef((event: KeyboardEvent) => {
    if (event.key !== 'Escape') return
    event.preventDefault()
    cancel.current()
  }).current

  const finish = (cancelled: boolean) => {
    if (!active.current) return
    // Cleared first, so that releasing the capture — which fires
    // lostpointercapture — cannot re-enter here.
    active.current = false

    const node = element.current
    if (node && pointerId.current !== null && node.hasPointerCapture(pointerId.current)) {
      node.releasePointerCapture(pointerId.current)
    }
    pointerId.current = null
    element.current = null
    document.body.classList.remove('is-resizing')
    document.removeEventListener('keydown', onKey, true)
    onEnd(cancelled)
  }
  cancel.current = () => finish(true)

  return {
    onPointerDown: (event) => {
      if (active.current) return
      if (!onStart(event)) return

      active.current = true
      pointerId.current = event.pointerId
      element.current = event.currentTarget
      event.currentTarget.setPointerCapture(event.pointerId)
      // While dragging, the cursor must not flicker as it passes over child
      // elements, and text under it must not select.
      document.body.classList.add('is-resizing')
      document.addEventListener('keydown', onKey, true)
      event.preventDefault()
    },

    onPointerMove: (event) => {
      if (!active.current) return
      onMove(event)
    },

    onPointerUp: () => finish(false),
    onPointerCancel: () => finish(true),
    // The browser can take the capture away — a context menu, a tab switch.
    // Treated as a cancel so nothing is left half-dragged.
    onLostPointerCapture: () => finish(true),
  }
}
