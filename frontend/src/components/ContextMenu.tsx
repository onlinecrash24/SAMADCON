/**
 * A right-click menu, the way MMC has one.
 *
 * Asked for by a tester: every action lived in a row of buttons one pane away
 * from the thing it acted on, and the habit people bring from RSAT is to
 * right-click the row.
 *
 * Portalled, necessarily. Both panes are `overflow: auto`, so a menu rendered
 * where it was opened would be clipped by the pane and would scroll with the
 * content underneath it.
 *
 * It dismisses when you click beside it — unlike the modal backdrop, which
 * deliberately does not. That is not an inconsistency to tidy up: a dialog can
 * hold half an hour of unsaved typing, and one did, and somebody lost it. A
 * menu holds nothing. See the comment in primitives.tsx before harmonising
 * these.
 */

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { popOverlay, pushOverlay } from './overlayStack'
import { useI18n } from '../i18n'
import type { MessageKey } from '../i18n/messages'

export interface MenuItem {
  id: string
  labelKey: MessageKey
  danger?: boolean
  children?: MenuItem[]
}

export type MenuNode = MenuItem | 'separator'

export interface MenuRequest {
  x: number
  y: number
  items: MenuNode[]
  onChoose: (id: string) => void
}

/** Distance kept from the viewport edge when the menu has to be nudged. */
const MARGIN = 8

export function ContextMenu({ request, onClose }: { request: MenuRequest; onClose: () => void }) {
  const { t } = useI18n()
  const ref = useRef<HTMLDivElement>(null)
  const [at, setAt] = useState({ x: request.x, y: request.y })
  const [openSub, setOpenSub] = useState<string | null>(null)

  const items = request.items.filter((node): node is MenuItem => node !== 'separator')

  useLayoutEffect(() => {
    const box = ref.current?.getBoundingClientRect()
    if (!box) return

    // Flipped rather than clamped, which is what Windows does: a menu shoved
    // back from the edge would sit under the pointer and swallow the next
    // click. Clamping is only the last resort, so it can never land off-screen
    // on a very small viewport.
    let x = request.x
    let y = request.y
    if (x + box.width > window.innerWidth - MARGIN) x = request.x - box.width
    if (y + box.height > window.innerHeight - MARGIN) y = request.y - box.height
    setAt({
      x: Math.max(MARGIN, Math.min(x, window.innerWidth - box.width - MARGIN)),
      y: Math.max(MARGIN, Math.min(y, window.innerHeight - box.height - MARGIN)),
    })
  }, [request.x, request.y])

  useEffect(() => {
    const token = pushOverlay(onClose)

    // Capture phase, so the click that dismisses the menu does not also
    // activate whatever it landed on. Scroll counts too: a menu anchored to a
    // row that has moved is pointing at the wrong thing.
    //
    // Which is why this has to ask where the press landed. A press on the
    // menu's own item is not an outside click, and the guard for that cannot
    // live on the menu: a React handler runs in the bubble phase from a
    // listener on the portal container, long after a capture listener on the
    // document has already fired. stopPropagation() there stops nothing that
    // has already run — the menu closed on pointerdown, the item was gone
    // before pointerup, and no click was ever produced. Every command in the
    // menu was dead to the mouse; only arrowing to an item and pressing Enter
    // worked, which is why a keyboard check passed it.
    const dismissOutside = (event: Event) => {
      const target = event.target
      if (target instanceof Node && ref.current?.contains(target)) return
      onClose()
    }
    // resize and blur have no target inside the menu to speak of.
    const dismissAlways = () => onClose()

    document.addEventListener('pointerdown', dismissOutside, true)
    document.addEventListener('scroll', dismissOutside, true)
    window.addEventListener('resize', dismissAlways)
    window.addEventListener('blur', dismissAlways)

    ref.current?.querySelector<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])')?.focus()

    return () => {
      popOverlay(token)
      document.removeEventListener('pointerdown', dismissOutside, true)
      document.removeEventListener('scroll', dismissOutside, true)
      window.removeEventListener('resize', dismissAlways)
      window.removeEventListener('blur', dismissAlways)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, per menu
  }, [])

  const move = (from: HTMLElement, step: number) => {
    const all = [...(ref.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])]
    const index = all.indexOf(from)
    if (index === -1 || all.length === 0) return
    const next = all[(index + step + all.length) % all.length]
    next?.focus()
  }

  const onKeyDown = (event: React.KeyboardEvent<HTMLElement>, node: MenuItem) => {
    const target = event.currentTarget
    if (event.key === 'ArrowDown') move(target, 1)
    else if (event.key === 'ArrowUp') move(target, -1)
    else if (event.key === 'Home' || event.key === 'End') {
      const all = [...(ref.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])]
      ;(event.key === 'Home' ? all[0] : all[all.length - 1])?.focus()
    } else if (event.key === 'ArrowRight' && node.children) {
      setOpenSub(node.id)
    } else if (event.key === 'ArrowLeft') {
      setOpenSub(null)
    } else if (event.key === 'Tab') {
      // Windows closes the menu and lets focus carry on.
      onClose()
      return
    } else {
      // First letter, as MMC does — useful in a menu of German verbs where
      // several start differently.
      const letter = event.key.toLowerCase()
      if (letter.length !== 1) return
      const all = [...(ref.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])]
      const match = all.find((el) => (el.textContent ?? '').trim().toLowerCase().startsWith(letter))
      if (!match) return
      match.focus()
    }
    event.preventDefault()
  }

  const choose = (id: string) => {
    onClose()
    request.onChoose(id)
  }

  const renderItem = (node: MenuItem) => (
    <div key={node.id} className="menu__row">
      <button
        type="button"
        role="menuitem"
        aria-haspopup={node.children ? 'menu' : undefined}
        aria-expanded={node.children ? openSub === node.id : undefined}
        className={node.danger ? 'menu__item menu__item--danger' : 'menu__item'}
        onClick={() => (node.children ? setOpenSub(openSub === node.id ? null : node.id) : choose(node.id))}
        onMouseEnter={() => setOpenSub(node.children ? node.id : null)}
        onKeyDown={(event) => onKeyDown(event, node)}
      >
        <span>{t(node.labelKey)}</span>
        {node.children && <span className="menu__arrow">▸</span>}
      </button>

      {node.children && openSub === node.id && (
        // One level, deliberately. See objectActions.ts.
        <div className="menu menu--sub" role="menu" aria-label={t(node.labelKey)}>
          {node.children.map((child) => (
            <button
              key={child.id}
              type="button"
              role="menuitem"
              className="menu__item"
              onClick={() => choose(child.id)}
              onKeyDown={(event) => onKeyDown(event, child)}
            >
              <span>{t(child.labelKey)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )

  return createPortal(
    <div
      ref={ref}
      className="menu"
      role="menu"
      aria-label={t('nav.actions')}
      style={{ left: at.x, top: at.y }}
    >
      {request.items.map((node, index) =>
        node === 'separator' ? (
          // Never first or last, where it would only draw a line against the
          // menu's own border.
          index === 0 || index === request.items.length - 1 ? null : (
            <div key={`sep-${index}`} className="menu__separator" role="separator" />
          )
        ) : (
          renderItem(node)
        ),
      )}
      {items.length === 0 && <div className="menu__empty">{t('detail.none')}</div>}
    </div>,
    document.getElementById('overlays') ?? document.body,
  )
}

/**
 * Holds the one open menu for a pane.
 *
 * One instance per pane, never one per row: a hook in every tree node would
 * mean hundreds of listeners for a menu that can only be open once.
 */
export function useContextMenu() {
  const [request, setRequest] = useState<MenuRequest | null>(null)

  return {
    /** Render this next to the pane. */
    menu: request ? <ContextMenu request={request} onClose={() => setRequest(null)} /> : null,
    open: (at: { x: number; y: number }, items: MenuNode[], onChoose: (id: string) => void) =>
      setRequest({ x: at.x, y: at.y, items, onChoose }),
    close: () => setRequest(null),
  }
}

/**
 * Where to put a menu opened from the keyboard.
 *
 * Shift+F10 and the menu key have no pointer position, so the row supplies
 * one. Without this the menu is not the keyboard equivalent of a right-click,
 * which is most of the reason for building it.
 */
export function anchorOf(element: HTMLElement): { x: number; y: number } {
  const box = element.getBoundingClientRect()
  return { x: box.left + 24, y: box.bottom - 4 }
}
