/**
 * Where the windows are drawn, and the bar that lists them.
 *
 * The layer is portalled for the same reason dialogs are: both panes are
 * `overflow: auto` and would clip anything positioned inside them. It sits in
 * its own stacking band below the dialogs, so a confirmation opened from a
 * window always lands on top of every window — including the one in front.
 *
 * The taskbar is an ordinary flex child of the console, not a fixed strip. The
 * console is already a column and the panes are already `flex: 1`, so a row at
 * the end simply takes its height and the panes shrink. Nothing is covered,
 * and there is no z-index to reason about.
 *
 * It lists only the active console's windows. That is what was asked for, and
 * it is the right scope — but it means "hidden" and "closed" look identical
 * from here, which is why the console tabs carry a count.
 */

import { createPortal } from 'react-dom'
import type { ReactNode } from 'react'

import { WindowFrame } from './WindowFrame'
import type { SnapinId } from '../features/console/snapins'
import { useI18n } from '../i18n'
import { useWindows, type ConsoleWindow } from '../state/windows'

export function WindowLayer({
  activeSnapin,
  render,
}: {
  activeSnapin: SnapinId
  /** Supplied by the shell, which knows what each kind of window contains. */
  render: (window: ConsoleWindow) => ReactNode
}) {
  const { windows, close, focus, toggleMinimised, toggleMaximised, move, resize } = useWindows()

  if (windows.length === 0) return null

  return createPortal(
    <div className="window-layer">
      {windows.map((window) => (
        <WindowFrame
          key={window.id}
          title={window.title}
          x={window.x}
          y={window.y}
          w={window.w}
          h={window.h}
          z={window.z}
          minimised={window.minimised}
          maximised={window.maximised}
          hidden={window.snapin !== activeSnapin || window.minimised}
          onFocus={() => focus(window.id)}
          onClose={() => close(window.id)}
          onMinimise={() => toggleMinimised(window.id)}
          onMaximise={() => toggleMaximised(window.id)}
          onMove={(at) => move(window.id, at)}
          onResize={(size) => resize(window.id, size)}
        >
          {render(window)}
        </WindowFrame>
      ))}
    </div>,
    document.getElementById('overlays') ?? document.body,
  )
}

export function Taskbar({ activeSnapin }: { activeSnapin: SnapinId }) {
  const { t } = useI18n()
  const { windows, focus, toggleMinimised } = useWindows()

  const mine = windows.filter((window) => window.snapin === activeSnapin)
  if (mine.length === 0) return null

  return (
    <div className="taskbar" role="toolbar" aria-label={t('window.taskbar')}>
      {mine.map((window) => (
        <button
          key={window.id}
          type="button"
          className={window.minimised ? 'taskbar__item taskbar__item--away' : 'taskbar__item'}
          title={window.title}
          aria-pressed={!window.minimised}
          // Clicking the one already in front puts it away, which is what a
          // taskbar button does everywhere else.
          onClick={() => (window.minimised ? focus(window.id) : toggleMinimised(window.id))}
        >
          {window.title}
        </button>
      ))}
    </div>
  )
}

/** How many windows each console is holding, for the tab strip. */
export function useWindowCounts(): Partial<Record<SnapinId, number>> {
  const { windows } = useWindows()
  const counts: Partial<Record<SnapinId, number>> = {}
  for (const window of windows) counts[window.snapin] = (counts[window.snapin] ?? 0) + 1
  return counts
}
