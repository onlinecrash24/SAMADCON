/** Small shared building blocks: icons, error display, modal shell, fields. */

import {
  useEffect,
  useRef,
  useSyncExternalStore,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'

import { ApiError } from '../api/client'
import { popOverlay, pushOverlay, subscribeToOverlays, topOverlay } from './overlayStack'
import { useI18n } from '../i18n'
import type { MessageKey } from '../i18n/messages'
import type { ObjectType } from '../api/types'

// ---------------------------------------------------------------------------
// Icons — inline SVG so the CSP needs no external sources
// ---------------------------------------------------------------------------

/**
 * The icons, each with the grid it was drawn on.
 *
 * Most come from Phosphor (regular weight, MIT) — see THIRD-PARTY-NOTICES.md.
 * They arrive as a single path on a 256 grid with fill:currentColor, which is
 * exactly the shape this already used, so nothing about how an icon is drawn
 * had to change.
 *
 * The viewBox travels with the path rather than sitting on the element,
 * because the set no longer comes from one place: the generic fallback is
 * still the hand-drawn one on a 24 grid, and a second grid arriving later
 * should cost nothing.
 */
const ICONS: Record<string, { box: string; d: string }> = {
  // Phosphor user
  user: { box: '0 0 256 256', d: 'M230.92,212c-15.23-26.33-38.7-45.21-66.09-54.16a72,72,0,1,0-73.66,0C63.78,166.78,40.31,185.66,25.08,212a8,8,0,1,0,13.85,8c18.84-32.56,52.14-52,89.07-52s70.23,19.44,89.07,52a8,8,0,1,0,13.85-8ZM72,96a56,56,0,1,1,56,56A56.06,56.06,0,0,1,72,96Z' },
  // Phosphor user-gear
  managed_service_account: { box: '0 0 256 256', d: 'M144,157.68a68,68,0,1,0-71.9,0c-20.65,6.76-39.23,19.39-54.17,37.17a8,8,0,1,0,12.24,10.3C50.25,181.19,77.91,168,108,168s57.75,13.19,77.87,37.15a8,8,0,0,0,12.26-10.3C183.18,177.07,164.6,164.44,144,157.68ZM56,100a52,52,0,1,1,52,52A52.06,52.06,0,0,1,56,100Zm196.25,43.07-4.66-2.69a23.6,23.6,0,0,0,0-8.76l4.66-2.69a8,8,0,1,0-8-13.86l-4.67,2.7a23.92,23.92,0,0,0-7.58-4.39V108a8,8,0,0,0-16,0v5.38a23.92,23.92,0,0,0-7.58,4.39l-4.67-2.7a8,8,0,1,0-8,13.86l4.66,2.69a23.6,23.6,0,0,0,0,8.76l-4.66,2.69a8,8,0,0,0,8,13.86l4.67-2.7a23.92,23.92,0,0,0,7.58,4.39V164a8,8,0,0,0,16,0v-5.38a23.92,23.92,0,0,0,7.58-4.39l4.67,2.7a7.92,7.92,0,0,0,4,1.07,8,8,0,0,0,4-14.93ZM216,136a8,8,0,1,1,8,8A8,8,0,0,1,216,136Z' },
  // Phosphor users
  group: { box: '0 0 256 256', d: 'M117.25,157.92a60,60,0,1,0-66.5,0A95.83,95.83,0,0,0,3.53,195.63a8,8,0,1,0,13.4,8.74,80,80,0,0,1,134.14,0,8,8,0,0,0,13.4-8.74A95.83,95.83,0,0,0,117.25,157.92ZM40,108a44,44,0,1,1,44,44A44.05,44.05,0,0,1,40,108Zm210.14,98.7a8,8,0,0,1-11.07-2.33A79.83,79.83,0,0,0,172,168a8,8,0,0,1,0-16,44,44,0,1,0-16.34-84.87,8,8,0,1,1-5.94-14.85,60,60,0,0,1,55.53,105.64,95.83,95.83,0,0,1,47.22,37.71A8,8,0,0,1,250.14,206.7Z' },
  // Phosphor desktop-tower
  computer: { box: '0 0 256 256', d: 'M216,72a8,8,0,0,1-8,8H176a8,8,0,0,1,0-16h32A8,8,0,0,1,216,72Zm-8,24H176a8,8,0,0,0,0,16h32a8,8,0,0,0,0-16Zm40-48V208a16,16,0,0,1-16,16H152a16,16,0,0,1-16-16V192H96v16h16a8,8,0,0,1,0,16H64a8,8,0,0,1,0-16H80V192H32A24,24,0,0,1,8,168V96A24,24,0,0,1,32,72H136V48a16,16,0,0,1,16-16h80A16,16,0,0,1,248,48ZM136,176V88H32a8,8,0,0,0-8,8v72a8,8,0,0,0,8,8Zm96,32V48H152V208h80Zm-40-40a12,12,0,1,0,12,12A12,12,0,0,0,192,168Z' },
  // Phosphor address-book
  contact: { box: '0 0 256 256', d: 'M83.19,174.4a8,8,0,0,0,11.21-1.6,52,52,0,0,1,83.2,0,8,8,0,1,0,12.8-9.6A67.88,67.88,0,0,0,163,141.51a40,40,0,1,0-53.94,0A67.88,67.88,0,0,0,81.6,163.2,8,8,0,0,0,83.19,174.4ZM112,112a24,24,0,1,1,24,24A24,24,0,0,1,112,112Zm96-88H64A16,16,0,0,0,48,40V64H32a8,8,0,0,0,0,16H48v40H32a8,8,0,0,0,0,16H48v40H32a8,8,0,0,0,0,16H48v24a16,16,0,0,0,16,16H208a16,16,0,0,0,16-16V40A16,16,0,0,0,208,24Zm0,192H64V40H208Z' },
  // Phosphor folder
  organizational_unit: { box: '0 0 256 256', d: 'M216,72H131.31L104,44.69A15.86,15.86,0,0,0,92.69,40H40A16,16,0,0,0,24,56V200.62A15.4,15.4,0,0,0,39.38,216H216.89A15.13,15.13,0,0,0,232,200.89V88A16,16,0,0,0,216,72ZM40,56H92.69l16,16H40ZM216,200H40V88H216Z' },
  // Phosphor folder-dashed
  container: { box: '0 0 256 256', d: 'M96,208a8,8,0,0,1-8,8H39.38A15.4,15.4,0,0,1,24,200.62V192a8,8,0,0,1,16,0v8H88A8,8,0,0,1,96,208Zm64-8H128a8,8,0,0,0,0,16h32a8,8,0,0,0,0-16Zm64-56a8,8,0,0,0-8,8v48H200a8,8,0,0,0,0,16h16.89A15.13,15.13,0,0,0,232,200.89V152A8,8,0,0,0,224,144Zm-8-72H168a8,8,0,0,0,0,16h48v24a8,8,0,0,0,16,0V88A16,16,0,0,0,216,72ZM24,80V56A16,16,0,0,1,40,40H92.69A15.86,15.86,0,0,1,104,44.69l29.66,29.65A8,8,0,0,1,128,88H32A8,8,0,0,1,24,80Zm16-8h68.69l-16-16H40Zm-8,88a8,8,0,0,0,8-8V120a8,8,0,0,0-16,0v32A8,8,0,0,0,32,160Z' },
  // Phosphor tree-structure
  domain: { box: '0 0 256 256', d: 'M160,112h48a16,16,0,0,0,16-16V48a16,16,0,0,0-16-16H160a16,16,0,0,0-16,16V64H128a24,24,0,0,0-24,24v32H72v-8A16,16,0,0,0,56,96H24A16,16,0,0,0,8,112v32a16,16,0,0,0,16,16H56a16,16,0,0,0,16-16v-8h32v32a24,24,0,0,0,24,24h16v16a16,16,0,0,0,16,16h48a16,16,0,0,0,16-16V160a16,16,0,0,0-16-16H160a16,16,0,0,0-16,16v16H128a8,8,0,0,1-8-8V88a8,8,0,0,1,8-8h16V96A16,16,0,0,0,160,112ZM56,144H24V112H56v32Zm104,16h48v48H160Zm0-112h48V96H160Z' },
  // Phosphor scroll
  gpo: { box: '0 0 256 256', d: 'M96,104a8,8,0,0,1,8-8h64a8,8,0,0,1,0,16H104A8,8,0,0,1,96,104Zm8,40h64a8,8,0,0,0,0-16H104a8,8,0,0,0,0,16Zm128,48a32,32,0,0,1-32,32H88a32,32,0,0,1-32-32V64a16,16,0,0,0-32,0c0,5.74,4.83,9.62,4.88,9.66h0A8,8,0,0,1,24,88a7.89,7.89,0,0,1-4.79-1.61h0C18.05,85.54,8,77.61,8,64A32,32,0,0,1,40,32H176a32,32,0,0,1,32,32V168h8a8,8,0,0,1,4.8,1.6C222,170.46,232,178.39,232,192ZM96.26,173.48A8.07,8.07,0,0,1,104,168h88V64a16,16,0,0,0-16-16H67.69A31.71,31.71,0,0,1,72,64V192a16,16,0,0,0,32,0c0-5.74-4.83-9.62-4.88-9.66A7.82,7.82,0,0,1,96.26,173.48ZM216,192a12.58,12.58,0,0,0-3.23-8h-94a26.92,26.92,0,0,1,1.21,8,31.82,31.82,0,0,1-4.29,16H200A16,16,0,0,0,216,192Z' },
  // Phosphor users-three
  'tab-directory': { box: '0 0 256 256', d: 'M244.8,150.4a8,8,0,0,1-11.2-1.6A51.6,51.6,0,0,0,192,128a8,8,0,0,1-7.37-4.89,8,8,0,0,1,0-6.22A8,8,0,0,1,192,112a24,24,0,1,0-23.24-30,8,8,0,1,1-15.5-4A40,40,0,1,1,219,117.51a67.94,67.94,0,0,1,27.43,21.68A8,8,0,0,1,244.8,150.4ZM190.92,212a8,8,0,1,1-13.84,8,57,57,0,0,0-98.16,0,8,8,0,1,1-13.84-8,72.06,72.06,0,0,1,33.74-29.92,48,48,0,1,1,58.36,0A72.06,72.06,0,0,1,190.92,212ZM128,176a32,32,0,1,0-32-32A32,32,0,0,0,128,176ZM72,120a8,8,0,0,0-8-8A24,24,0,1,1,87.24,82a8,8,0,1,0,15.5-4A40,40,0,1,0,37,117.51,67.94,67.94,0,0,0,9.6,139.19a8,8,0,1,0,12.8,9.61A51.6,51.6,0,0,1,64,128,8,8,0,0,0,72,120Z' },
  // Phosphor globe-hemisphere-west
  'tab-dns': { box: '0 0 256 256', d: 'M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm88,104a87.62,87.62,0,0,1-6.4,32.94l-44.7-27.49a15.92,15.92,0,0,0-6.24-2.23l-22.82-3.08a16.11,16.11,0,0,0-16,7.86h-8.72l-3.8-7.86a15.91,15.91,0,0,0-11-8.67l-8-1.73L96.14,104h16.71a16.06,16.06,0,0,0,7.73-2l12.25-6.76a16.62,16.62,0,0,0,3-2.14l26.91-24.34A15.93,15.93,0,0,0,166,49.1l-.36-.65A88.11,88.11,0,0,1,216,128ZM143.31,41.34,152,56.9,125.09,81.24,112.85,88H96.14a16,16,0,0,0-13.88,8l-8.73,15.23L63.38,84.19,74.32,58.32a87.87,87.87,0,0,1,69-17ZM40,128a87.53,87.53,0,0,1,8.54-37.8l11.34,30.27a16,16,0,0,0,11.62,10l21.43,4.61L96.74,143a16.09,16.09,0,0,0,14.4,9h1.48l-7.23,16.23a16,16,0,0,0,2.86,17.37l.14.14L128,205.94l-1.94,10A88.11,88.11,0,0,1,40,128Zm102.58,86.78,1.13-5.81a16.09,16.09,0,0,0-4-13.9,1.85,1.85,0,0,1-.14-.14L120,174.74,133.7,144l22.82,3.08,45.72,28.12A88.18,88.18,0,0,1,142.58,214.78Z' },
  // Phosphor graph
  'tab-sites': { box: '0 0 256 256', d: 'M200,152a31.84,31.84,0,0,0-19.53,6.68l-23.11-18A31.65,31.65,0,0,0,160,128c0-.74,0-1.48-.08-2.21l13.23-4.41A32,32,0,1,0,168,104c0,.74,0,1.48.08,2.21l-13.23,4.41A32,32,0,0,0,128,96a32.59,32.59,0,0,0-5.27.44L115.89,81A32,32,0,1,0,96,88a32.59,32.59,0,0,0,5.27-.44l6.84,15.4a31.92,31.92,0,0,0-8.57,39.64L73.83,165.44a32.06,32.06,0,1,0,10.63,12l25.71-22.84a31.91,31.91,0,0,0,37.36-1.24l23.11,18A31.65,31.65,0,0,0,168,184a32,32,0,1,0,32-32Zm0-64a16,16,0,1,1-16,16A16,16,0,0,1,200,88ZM80,56A16,16,0,1,1,96,72,16,16,0,0,1,80,56ZM56,208a16,16,0,1,1,16-16A16,16,0,0,1,56,208Zm56-80a16,16,0,1,1,16,16A16,16,0,0,1,112,128Zm88,72a16,16,0,1,1,16-16A16,16,0,0,1,200,200Z' },
  // Phosphor pulse
  'tab-diagnostics': { box: '0 0 256 256', d: 'M240,128a8,8,0,0,1-8,8H204.94l-37.78,75.58A8,8,0,0,1,160,216h-.4a8,8,0,0,1-7.08-5.14L95.35,60.76,63.28,131.31A8,8,0,0,1,56,136H24a8,8,0,0,1,0-16H50.85L88.72,36.69a8,8,0,0,1,14.76.46l57.51,151,31.85-63.71A8,8,0,0,1,200,120h32A8,8,0,0,1,240,128Z' },
  // Phosphor scroll
  'tab-gpo': { box: '0 0 256 256', d: 'M96,104a8,8,0,0,1,8-8h64a8,8,0,0,1,0,16H104A8,8,0,0,1,96,104Zm8,40h64a8,8,0,0,0,0-16H104a8,8,0,0,0,0,16Zm128,48a32,32,0,0,1-32,32H88a32,32,0,0,1-32-32V64a16,16,0,0,0-32,0c0,5.74,4.83,9.62,4.88,9.66h0A8,8,0,0,1,24,88a7.89,7.89,0,0,1-4.79-1.61h0C18.05,85.54,8,77.61,8,64A32,32,0,0,1,40,32H176a32,32,0,0,1,32,32V168h8a8,8,0,0,1,4.8,1.6C222,170.46,232,178.39,232,192ZM96.26,173.48A8.07,8.07,0,0,1,104,168h88V64a16,16,0,0,0-16-16H67.69A31.71,31.71,0,0,1,72,64V192a16,16,0,0,0,32,0c0-5.74-4.83-9.62-4.88-9.66A7.82,7.82,0,0,1,96.26,173.48ZM216,192a12.58,12.58,0,0,0-3.23-8h-94a26.92,26.92,0,0,1,1.21,8,31.82,31.82,0,0,1-4.29,16H200A16,16,0,0,0,216,192Z' },
  // Phosphor chart-bar
  'tab-reports': { box: '0 0 256 256', d: 'M224,200h-8V40a8,8,0,0,0-8-8H152a8,8,0,0,0-8,8V80H96a8,8,0,0,0-8,8v40H48a8,8,0,0,0-8,8v64H32a8,8,0,0,0,0,16H224a8,8,0,0,0,0-16ZM160,48h40V200H160ZM104,96h40V200H104ZM56,144H88v56H56Z' },
  // The only one that is not Phosphor: what an object with no icon of
  // its own gets, drawn here and on the older grid.
  object: {
    box: '0 0 24 24',
    d: 'M12 2l9 5v10l-9 5-9-5V7l9-5zm0 2.3L5 8.2v7.6l7 3.9 7-3.9V8.2l-7-3.9z',
  },
}

const TYPE_ICON: Record<string, string> = {
  user: 'user',
  managed_service_account: 'managed_service_account',
  group: 'group',
  computer: 'computer',
  organizational_unit: 'organizational_unit',
  container: 'container',
  builtin: 'container',
  domain: 'domain',
  contact: 'contact',
  gpo: 'gpo',
}

/**
 * One icon, named either by what an object *is* or by which icon is wanted.
 *
 * Both, because the console tabs have always passed an icon name into this
 * prop and it only worked by accident — the three they used happened to be
 * spelled the same as three object types. Now that each tab has its own, the
 * coincidence runs out.
 */
export function Icon({ type, className }: { type: ObjectType | string; className?: string }) {
  const icon = ICONS[TYPE_ICON[type] ?? type] ?? ICONS.object!
  return (
    <svg
      className={className ? `icon ${className}` : 'icon'}
      viewBox={icon.box}
      aria-hidden="true"
      focusable="false"
    >
      <path d={icon.d} />
    </svg>
  )
}

export function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      className={open ? 'chevron chevron--open' : 'chevron'}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M9 6l6 6-6 6" />
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

export function ErrorMessage({ error, onDismiss }: { error: unknown; onDismiss?: () => void }) {
  const { t, te, th } = useI18n()
  if (!error) return null

  const hint = th(error)
  const detail = error instanceof ApiError ? error.detail : undefined

  return (
    <div className="alert alert--error" role="alert">
      <div className="alert__body">
        <strong>{te(error)}</strong>
        {hint && (
          <p className="alert__hint">
            {t('error.hint')}: {hint}
          </p>
        )}
        {detail && (
          <details className="alert__details">
            <summary>{t('error.details')}</summary>
            <code>{detail}</code>
          </details>
        )}
      </div>
      {onDismiss && (
        <button type="button" className="alert__close" onClick={onDismiss} aria-label="×">
          ×
        </button>
      )}
    </div>
  )
}

export function Banner({ message, tone = 'info' }: { message: string; tone?: 'info' | 'warning' }) {
  return <div className={`alert alert--${tone}`}>{message}</div>
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

/**
 * Anything that can hold focus, in document order.
 *
 * Queried each time rather than cached when the dialog opens: the object
 * picker inside the membership editor, and both dialogs in the security tab,
 * mount their fields after the dialog exists. A list taken at open would trap
 * focus in the two buttons that happened to be there first.
 */
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]),' +
  ' textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/** The host every overlay is portalled into. See index.html. */
function overlayHost(): HTMLElement {
  return document.getElementById('overlays') ?? document.body
}

export function Modal({
  title,
  onClose,
  children,
  footer,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
}) {
  // There used to be a `size` for the one dialog that wanted the screen — a
  // tree beside a list of settings. That is a window now, with a title bar and
  // a position, so the option described a shape this component no longer has.
  // Every dialog here is a form or a confirmation.
  const ref = useRef<HTMLDivElement>(null)
  const token = useRef(0)

  // Read from a ref so that registering can happen once, on mount, without the
  // stack entry going stale when the caller passes a new arrow each render.
  const close = useRef(onClose)
  close.current = onClose

  useEffect(() => {
    token.current = pushOverlay(() => close.current())

    // Where focus was, so it can be handed back. Moving focus into the dialog
    // is required — a keyboard user left outside an aria-modal dialog has
    // nowhere to go — but never returning it is how people end up back at the
    // top of the page after every confirmation.
    const opener = document.activeElement as HTMLElement | null
    ref.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus()

    return () => {
      popOverlay(token.current)
      token.current = 0
      // Only if focus is still ours to give back. If the person has clicked
      // elsewhere in the meantime, yanking it would be the rude thing.
      if (opener && ref.current?.contains(document.activeElement)) opener.focus()
    }
  }, [])

  // Only the topmost overlay tints the page. Two dialogs each drawing 45%
  // black gave 70%, and the one underneath became unreadable in a pair while
  // being perfectly legible alone.
  const top = useSyncExternalStore(subscribeToOverlays, topOverlay, () => 0)
  const isTop = token.current !== 0 && token.current === top

  // aria-modal is asserted below, so Tab has to honour it. It did not: focus
  // walked straight out into the console behind. Portalling made that worse —
  // the dialog is no longer even in the console's document order.
  const trapFocus = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Tab' || !ref.current) return
    const items = [...ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)]
    if (items.length === 0) return

    const first = items[0]!
    const last = items[items.length - 1]!
    const active = document.activeElement

    if (event.shiftKey && active === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && active === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return createPortal(
    // Portalled out of wherever it was used, and this is load-bearing rather
    // than tidiness: a dialog rendered inside a positioned window resolves its
    // z-index within that window's stacking context, so a confirmation opened
    // from a background window would paint underneath the window in front.
    // Silently.
    //
    // The backdrop does nothing on click, on purpose, and this is not an
    // omission to be tidied up later. It used to close the dialog on
    // mousedown, which meant a click landing slightly wide of the policy
    // editor threw away everything typed into it, without a word. Reported by
    // someone who lost work to it.
    //
    // Windows dialogs do not close when you click beside them either, and this
    // console is read against those.
    <div className={isTop ? 'modal__backdrop' : 'modal__backdrop modal__backdrop--stacked'}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        ref={ref}
        onKeyDown={trapFocus}
      >
        <header className="modal__header">
          <h2>{title}</h2>
          <button type="button" className="modal__close" onClick={onClose} aria-label="×">
            ×
          </button>
        </header>
        <div className="modal__body">{children}</div>
        {footer && <footer className="modal__footer">{footer}</footer>}
      </div>
    </div>,
    overlayHost(),
  )
}

// ---------------------------------------------------------------------------
// Form fields
// ---------------------------------------------------------------------------

export function Field({
  label,
  children,
  hint,
}: {
  label: string
  children: ReactNode
  hint?: string
}) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      {children}
      {hint && <span className="field__hint">{hint}</span>}
    </label>
  )
}

export function TextRow({ label, value }: { label: string; value: ReactNode }) {
  if (value === null || value === undefined || value === '') return null
  return (
    <div className="row">
      <span className="row__label">{label}</span>
      <span className="row__value">{value}</span>
    </div>
  )
}

export function Badge({ tone, children }: { tone: 'ok' | 'warn' | 'danger' | 'muted'; children: ReactNode }) {
  return <span className={`badge badge--${tone}`}>{children}</span>
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="spinner" role="status">
      <span className="spinner__dot" />
      {label && <span>{label}</span>}
    </div>
  )
}

/** Format an ISO timestamp in the user's locale, or a dash when absent. */
export function useDateFormat() {
  const { language } = useI18n()
  return (value: string | null | undefined): string => {
    if (!value) return '—'
    const parsed = new Date(value)
    if (Number.isNaN(parsed.getTime())) return '—'
    return parsed.toLocaleString(language === 'de' ? 'de-DE' : 'en-GB', {
      dateStyle: 'medium',
      timeStyle: 'short',
    })
  }
}

export function useTypeLabel() {
  const { t } = useI18n()
  return (type: ObjectType | string): string => t(`type.${type}` as MessageKey)
}
