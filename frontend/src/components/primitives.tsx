/** Small shared building blocks: icons, error display, modal shell, fields. */

import { useEffect, useRef, type ReactNode } from 'react'

import { ApiError } from '../api/client'
import { useI18n } from '../i18n'
import type { MessageKey } from '../i18n/messages'
import type { ObjectType } from '../api/types'

// ---------------------------------------------------------------------------
// Icons — inline SVG so the CSP needs no external sources
// ---------------------------------------------------------------------------

const ICON_PATHS: Record<string, string> = {
  user: 'M12 12a4 4 0 100-8 4 4 0 000 8zm0 2c-4 0-7 2-7 4.5V21h14v-2.5C19 16 16 14 12 14z',
  group:
    'M8 12a3 3 0 100-6 3 3 0 000 6zm8 0a3 3 0 100-6 3 3 0 000 6zM2 20v-1.5C2 16 4.7 14 8 14s6 2 6 4.5V20H2zm14 0v-1.5c0-1.4-.6-2.6-1.5-3.4.5-.1 1-.1 1.5-.1 3.3 0 6 2 6 4.5V20h-6z',
  computer:
    'M3 5h18a1 1 0 011 1v10a1 1 0 01-1 1H3a1 1 0 01-1-1V6a1 1 0 011-1zm1 2v8h16V7H4zM8 19h8v2H8v-2z',
  organizational_unit: 'M4 4h6l2 2h8v12H4V4zm2 4v8h12V8H6z',
  container: 'M4 4h16v4H4V4zm0 6h16v10H4V10zm2 2v6h12v-6H6z',
  domain:
    'M12 2a10 10 0 100 20 10 10 0 000-20zm0 2c1.7 0 3.2 2.6 3.8 6H8.2C8.8 6.6 10.3 4 12 4zM4.3 10h3.4a22 22 0 000 4H4.3a8 8 0 010-4zm0 6h3.9c.6 2.5 1.6 4.3 2.6 5a8 8 0 01-6.5-5zm5.6 0h4.2c-.6 3-1.9 5-2.1 5s-1.5-2-2.1-5zm6.2 0h3.6a8 8 0 01-6.5 5c1-.7 2-2.5 2.6-5zm.2-2a22 22 0 000-4h3.4a8 8 0 010 4h-3.4z',
  contact: 'M12 12a4 4 0 100-8 4 4 0 000 8zm-8 9v-1c0-3 4-5 8-5s8 2 8 5v1H4z',
  gpo: 'M12 2l8 4v6c0 5-3.4 8.7-8 10-4.6-1.3-8-5-8-10V6l8-4zm0 4L7 8v4c0 3.3 2 6.1 5 7.2 3-1.1 5-3.9 5-7.2V8l-5-2z',
  object: 'M12 2l9 5v10l-9 5-9-5V7l9-5zm0 2.3L5 8.2v7.6l7 3.9 7-3.9V8.2l-7-3.9z',
}

const TYPE_ICON: Record<string, string> = {
  user: 'user',
  managed_service_account: 'user',
  group: 'group',
  computer: 'computer',
  organizational_unit: 'organizational_unit',
  container: 'container',
  builtin: 'container',
  domain: 'domain',
  contact: 'contact',
  gpo: 'gpo',
}

export function Icon({ type, className }: { type: ObjectType | string; className?: string }) {
  const key = TYPE_ICON[type] ?? 'object'
  return (
    <svg
      className={className ? `icon ${className}` : 'icon'}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <path d={ICON_PATHS[key] ?? ICON_PATHS.object!} />
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

export function Modal({
  title,
  onClose,
  children,
  footer,
  size = 'normal',
}: {
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  /**
   * A form asking for one name wants to stay small. A console window — a tree
   * beside a list of settings — wants the screen, because the alternative is
   * scrolling two panes inside a box.
   */
  size?: 'normal' | 'console'
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    // Move focus into the dialog so keyboard users are not left outside it.
    ref.current?.querySelector<HTMLElement>('input, select, textarea, button')?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal__backdrop" onMouseDown={onClose}>
      <div
        className={size === 'console' ? 'modal modal--console' : 'modal'}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        ref={ref}
        onMouseDown={(event) => event.stopPropagation()}
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
    </div>
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
