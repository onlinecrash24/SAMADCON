/**
 * Asking before an administrator is disabled.
 *
 * Shown when the server refuses to disable an account that administers the
 * domain without an explicit confirmation. The box has to be ticked before the
 * button does anything: a second click on the same spot is not a decision,
 * and the one account left that could sign in may be this one.
 */

import { useState } from 'react'

import { Modal } from '../../components/primitives'
import { useI18n } from '../../i18n'
import { isBuiltinAdministrator, type AdminRefusal } from './adminDisable'

export function ConfirmAdminDisable({
  name,
  refusal,
  pending,
  onCancel,
  onConfirm,
}: {
  /** The name the console shows for the account. */
  name: string
  refusal: AdminRefusal
  pending: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const { t } = useI18n()
  const [understood, setUnderstood] = useState(false)

  return (
    <Modal
      title={t('admin.disableTitle')}
      onClose={onCancel}
      footer={
        <>
          <button type="button" className="button" onClick={onCancel}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--danger"
            disabled={!understood || pending}
            onClick={onConfirm}
          >
            {pending ? t('status.loading') : t('action.disable')}
          </button>
        </>
      }
    >
      <div className="stack-tight">
        <p>
          {isBuiltinAdministrator(refusal)
            ? t('admin.disableBuiltin', { name })
            : t('admin.disableMember', { name, role: refusal.role })}
        </p>
        <p className="muted">{t('admin.disableConsequence')}</p>
        <pre className="payload mono small">{`samba-tool user enable ${refusal.account ?? name}`}</pre>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={understood}
            onChange={(event) => setUnderstood(event.target.checked)}
          />
          <span>{t('admin.disableConfirm')}</span>
        </label>
      </div>
    </Modal>
  )
}
