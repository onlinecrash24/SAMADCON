/**
 * The line between two panes, and a handle for moving it.
 *
 * Asked for by a tester: a large directory needs a wide tree, a wide policy
 * name needs a wide list, and until now both were fixed in the stylesheet.
 *
 * The width is written as a custom property on the grid container, never as an
 * inline `grid-template-columns`. That distinction is the whole design. An
 * inline `grid-template-columns` is a declaration, and it would beat every
 * media query short of `!important` — so the narrow layouts would silently
 * stop working the moment anyone dragged anything, and nobody would notice
 * until a laptop complained. A custom property is only a *value*; the media
 * queries set the columns themselves and never read it.
 *
 * The second payoff: resetting means *deleting* the property, after which the
 * stylesheet's own `minmax()` applies again. The default is written down in
 * exactly one place, and this component does not know it.
 *
 * During a drag the property is written straight onto the DOM node rather than
 * through React state. A pointer move can fire every frame, and re-rendering
 * three panes and a tree that often is a lot of work to move a line.
 */

import { useLayoutEffect, useRef, useState } from 'react'

import { useI18n } from '../i18n'
import { clampWidth, LIMITS, LIST_MIN, type Boundary } from '../state/paneWidths'
import { usePointerDrag } from './usePointerDrag'

const STEP = 16
const SEPARATOR = 5

export function Splitter({
  boundary,
  onCommit,
}: {
  boundary: Boundary
  /** Called once, on release — never per move. */
  onCommit: (px: number | null) => void
}) {
  const { t } = useI18n()
  const ref = useRef<HTMLDivElement>(null)
  const start = useRef({ x: 0, width: 0, upper: LIMITS[boundary].max })

  // Only for the screen reader: aria-valuenow has to be a number, and the
  // width usually comes from the stylesheet rather than from stored state.
  // Measured, therefore — once at mount and after each change.
  const [announced, setAnnounced] = useState<number | null>(null)

  const panes = () => ref.current?.parentElement ?? null
  const neighbour = () =>
    panes()?.querySelector<HTMLElement>(boundary === 'tree' ? '.pane--tree' : '.pane--detail') ??
    null

  const measure = () => Math.round(neighbour()?.getBoundingClientRect().width ?? 0)

  useLayoutEffect(() => {
    setAnnounced(measure())
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, on mount
  }, [])

  /**
   * The most this boundary may take.
   *
   * The list track is `minmax(340px, 1fr)`, so a tree and a detail pane that
   * together leave less than that make the grid overflow instead of squeezing.
   * Measured once when the drag starts, not on every move.
   */
  const roomFor = (): number => {
    const container = panes()
    if (!container) return LIMITS[boundary].max

    const other = container.querySelector<HTMLElement>(
      boundary === 'tree' ? '.pane--detail' : '.pane--tree',
    )
    const otherWidth = other ? other.getBoundingClientRect().width : 0
    const separators = SEPARATOR * container.querySelectorAll('.splitter').length
    const room = container.getBoundingClientRect().width - LIST_MIN - separators - otherWidth
    return Math.min(LIMITS[boundary].max, Math.max(LIMITS[boundary].min, room))
  }

  const write = (px: number) => {
    panes()?.style.setProperty(`--${boundary}-w`, `${px}px`)
  }

  const drag = usePointerDrag({
    onStart: (event) => {
      if (event.button !== 0) return false
      start.current = { x: event.clientX, width: measure(), upper: roomFor() }
      return true
    },
    onMove: (event) => {
      // The tree grows to the right, the detail pane to the left.
      const delta = boundary === 'tree' ? event.clientX - start.current.x : start.current.x - event.clientX
      const next = Math.min(
        start.current.upper,
        Math.max(LIMITS[boundary].min, start.current.width + delta),
      )
      write(Math.round(next))
    },
    onEnd: (cancelled) => {
      if (cancelled) {
        write(start.current.width)
        setAnnounced(start.current.width)
        return
      }
      const settled = measure()
      setAnnounced(settled)
      onCommit(settled)
    },
  })

  const nudge = (px: number) => {
    const next = clampWidth(boundary, Math.min(roomFor(), px))
    write(next)
    setAnnounced(next)
    onCommit(next)
  }

  const reset = () => {
    // Deleting the property, not writing a default: the default lives in the
    // stylesheet and this component must not hold a second copy of it.
    panes()?.style.removeProperty(`--${boundary}-w`)
    onCommit(null)
    requestAnimationFrame(() => setAnnounced(measure()))
  }

  return (
    <div
      ref={ref}
      className={`splitter splitter--${boundary}`}
      role="separator"
      aria-orientation="vertical"
      aria-label={t(boundary === 'tree' ? 'splitter.tree' : 'splitter.detail')}
      aria-valuenow={announced ?? undefined}
      aria-valuemin={LIMITS[boundary].min}
      aria-valuemax={LIMITS[boundary].max}
      tabIndex={0}
      title={t('splitter.hint')}
      onDoubleClick={reset}
      onKeyDown={(event) => {
        const current = measure()
        if (event.key === 'ArrowLeft') nudge(boundary === 'tree' ? current - STEP : current + STEP)
        else if (event.key === 'ArrowRight') nudge(boundary === 'tree' ? current + STEP : current - STEP)
        else if (event.key === 'Home') nudge(LIMITS[boundary].min)
        else if (event.key === 'End') nudge(LIMITS[boundary].max)
        else if (event.key === 'Enter' || event.key === ' ') reset()
        else return
        event.preventDefault()
      }}
      {...drag}
    />
  )
}
