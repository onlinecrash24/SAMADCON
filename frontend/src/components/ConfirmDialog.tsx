/**
 * "Are you sure?" before a write that one click should not do on its own:
 * removing a link, a redirection or a script, resetting a computer account,
 * switching a WMI filter.
 *
 * Cancel comes first, so the keyboard lands on the harmless choice. The
 * dialog stays open while the write runs and shows its error, so a refusal
 * is not lost behind a closed window.
 */

import type { ReactNode } from 'react'

import { useI18n } from '../i18n'
import { ErrorMessage, Modal } from './primitives'

export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  danger = true,
  pending = false,
  error,
  onConfirm,
  onCancel,
}: {
  title: string
  children: ReactNode
  confirmLabel: string
  /** Drawn as destructive; false for a change that is not a removal. */
  danger?: boolean
  pending?: boolean
  error?: unknown
  onConfirm: () => void
  onCancel: () => void
}) {
  const { t } = useI18n()
  return (
    <Modal
      title={title}
      onClose={onCancel}
      footer={
        <>
          <button type="button" className="button" onClick={onCancel}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className={danger ? 'button button--danger' : 'button button--primary'}
            disabled={pending}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </>
      }
    >
      <div className="form">
        <ErrorMessage error={error} />
        {children}
      </div>
    </Modal>
  )
}
