/**
 * A window: a title bar you can drag, a body, and a corner you can pull.
 *
 * Beside Modal rather than made out of it. They differ on every axis — centred
 * against positioned, backdrop against none, focus-trapped against not,
 * Escape-dismissed against not, meant to be one against meant to be several.
 * Merged, every one of the twenty-six existing dialogs would become a
 * configuration puzzle, and Modal's signature would have to change to say
 * which kind it is.
 *
 * Escape does not close a window. Windows closes dialogs with Escape and
 * windows with a deliberate gesture, and a property window can be holding
 * unsaved edits — which is the loss this console already had reported once.
 *
 * Geometry goes in custom properties rather than inline styles, so the narrow
 * layout can override it. An inline width would beat the media query, and
 * windows on a phone would stay draggable little boxes instead of becoming
 * full screen.
 */

import { useRef, type ReactNode } from 'react'

import { usePointerDrag } from './usePointerDrag'
import { useI18n } from '../i18n'
import { MIN_SIZE } from '../state/windows'

/** Kept on screen, so a window dragged too far can always be caught again. */
const VISIBLE_EDGE = 80

export interface WindowFrameProps {
  title: string
  x: number
  y: number
  w: number
  h: number
  z: number
  minimised: boolean
  maximised: boolean
  hidden: boolean
  onFocus: () => void
  onClose: () => void
  onMinimise: () => void
  onMaximise: () => void
  onMove: (at: { x: number; y: number }) => void
  onResize: (size: { w: number; h: number }) => void
  children: ReactNode
}

export function WindowFrame({
  title,
  x,
  y,
  w,
  h,
  z,
  minimised,
  maximised,
  hidden,
  onFocus,
  onClose,
  onMinimise,
  onMaximise,
  onMove,
  onResize,
  children,
}: WindowFrameProps) {
  const { t } = useI18n()
  const ref = useRef<HTMLDivElement>(null)
  const from = useRef({ px: 0, py: 0, x: 0, y: 0, w: 0, h: 0 })

  const write = (name: string, value: number) => {
    ref.current?.style.setProperty(`--win-${name}`, `${Math.round(value)}px`)
  }

  const dragTitle = usePointerDrag({
    onStart: (event) => {
      if (event.button !== 0 || maximised) return false
      // Minimise, maximise and close live in this bar. Starting a drag would
      // capture the pointer to the bar, so the release never reaches the
      // button and no click is ever produced — the three of them were dead.
      if ((event.target as HTMLElement).closest('button')) return false
      onFocus()
      from.current = { px: event.clientX, py: event.clientY, x, y, w, h }
      return true
    },
    onMove: (event) => {
      const nextX = from.current.x + (event.clientX - from.current.px)
      const nextY = from.current.y + (event.clientY - from.current.py)
      // Never so far that the bar cannot be grabbed again.
      write('x', Math.min(window.innerWidth - VISIBLE_EDGE, Math.max(-w + VISIBLE_EDGE, nextX)))
      write('y', Math.min(window.innerHeight - 32, Math.max(0, nextY)))
    },
    onEnd: (cancelled) => {
      if (cancelled) {
        write('x', from.current.x)
        write('y', from.current.y)
        return
      }
      const box = ref.current?.getBoundingClientRect()
      if (box) onMove({ x: Math.round(box.left), y: Math.round(box.top) })
    },
  })

  const dragCorner = usePointerDrag({
    onStart: (event) => {
      if (event.button !== 0 || maximised) return false
      onFocus()
      from.current = { px: event.clientX, py: event.clientY, x, y, w, h }
      return true
    },
    onMove: (event) => {
      write('w', Math.max(MIN_SIZE.w, from.current.w + (event.clientX - from.current.px)))
      write('h', Math.max(MIN_SIZE.h, from.current.h + (event.clientY - from.current.py)))
    },
    onEnd: (cancelled) => {
      if (cancelled) {
        write('w', from.current.w)
        write('h', from.current.h)
        return
      }
      const box = ref.current?.getBoundingClientRect()
      if (box) onResize({ w: Math.round(box.width), h: Math.round(box.height) })
    },
  })

  const classes = ['window']
  if (maximised) classes.push('window--maximised')
  if (minimised) classes.push('window--minimised')

  return (
    <div
      ref={ref}
      className={classes.join(' ')}
      role="dialog"
      aria-label={title}
      // Hidden rather than unmounted while another console is open: a
      // half-typed property sheet and a write in flight both have to survive
      // someone glancing elsewhere.
      hidden={hidden}
      style={
        {
          '--win-x': `${x}px`,
          '--win-y': `${y}px`,
          '--win-w': `${w}px`,
          '--win-h': `${h}px`,
          zIndex: z,
        } as React.CSSProperties
      }
      onPointerDownCapture={onFocus}
    >
      <header className="window__bar" onDoubleClick={onMaximise} {...dragTitle}>
        <span className="window__title" title={title}>
          {title}
        </span>
        <div className="window__buttons">
          <button
            type="button"
            className="window__button"
            onClick={onMinimise}
            aria-label={t('window.minimise')}
            title={t('window.minimise')}
          >
            –
          </button>
          <button
            type="button"
            className="window__button"
            onClick={onMaximise}
            aria-label={t('window.maximise')}
            title={t('window.maximise')}
          >
            ▢
          </button>
          <button
            type="button"
            className="window__button window__button--close"
            onClick={onClose}
            aria-label={t('action.close')}
            title={t('action.close')}
          >
            ×
          </button>
        </div>
      </header>

      <div className="window__body">{children}</div>

      {!maximised && (
        <div
          className="window__corner"
          aria-label={t('window.resize')}
          role="separator"
          {...dragCorner}
        />
      )}
    </div>
  )
}
