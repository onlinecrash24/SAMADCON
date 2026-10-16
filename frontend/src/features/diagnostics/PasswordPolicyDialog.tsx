/**
 * Editing the domain's password and lockout policy.
 *
 * On a Samba DC these values on the domain object are what domain accounts
 * are held to; the Default Domain Policy is not copied onto them, as a
 * Windows DC would. This is `samba-tool domain passwordsettings set`, with
 * the same ranges, checked by the server.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import type { PasswordPolicy } from '../../api/types'
import { ErrorMessage, Field, Modal } from '../../components/primitives'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n/messages'
import { changesBetween, draftFrom, type PolicyDraft } from './passwordPolicyDraft'

const NUMBER_FIELDS: { field: keyof PolicyDraft; label: MessageKey; hint?: MessageKey }[] = [
  { field: 'min_length', label: 'diag.minLength' },
  { field: 'history_length', label: 'diag.history' },
  { field: 'min_age_days', label: 'diag.minAgeDays', hint: 'diag.policyEdit.zeroNone' },
  { field: 'max_age_days', label: 'diag.maxAgeDays', hint: 'diag.policyEdit.zeroNever' },
  { field: 'lockout_threshold', label: 'diag.lockoutThreshold', hint: 'diag.policyEdit.zeroNoLockout' },
  {
    field: 'lockout_duration_minutes',
    label: 'diag.lockoutDurationMinutes',
    hint: 'diag.policyEdit.zeroUntilAdmin',
  },
  { field: 'lockout_window_minutes', label: 'diag.lockoutWindowMinutes' },
]

export function PasswordPolicyDialog({
  policy,
  onClose,
  onSaved,
}: {
  policy: PasswordPolicy
  onClose: () => void
  onSaved: (message: string) => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<PolicyDraft>(() => draftFrom(policy))
  const changes = changesBetween(policy, draft)

  const save = useMutation({
    mutationFn: () => api.setPasswordPolicy(changes ?? {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['diagnostics'] })
      onSaved(t('status.saved'))
      onClose()
    },
  })

  const nothing = changes !== null && Object.keys(changes).length === 0

  return (
    <Modal
      title={t('diag.policyEdit.title')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={save.isPending || changes === null || nothing}
            onClick={() => save.mutate()}
          >
            {t('action.save')}
          </button>
        </>
      }
    >
      <div className="form">
        <ErrorMessage error={save.error} />
        <p className="muted small">{t('diag.policyEdit.intro')}</p>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={draft.complexity}
            onChange={(event) => setDraft({ ...draft, complexity: event.target.checked })}
          />
          <span>{t('diag.complexity')}</span>
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={draft.reversible_encryption}
            onChange={(event) =>
              setDraft({ ...draft, reversible_encryption: event.target.checked })
            }
          />
          <span>{t('diag.policyEdit.reversible')}</span>
        </label>
        {draft.reversible_encryption && !policy.reversible_encryption && (
          <div className="alert alert--warning">{t('diag.reversibleWarning')}</div>
        )}
        {NUMBER_FIELDS.map(({ field, label, hint }) => (
          <Field key={field} label={t(label)} hint={hint ? t(hint) : undefined}>
            <input
              type="number"
              min={0}
              step={1}
              inputMode="numeric"
              value={draft[field] as string}
              onChange={(event) => setDraft({ ...draft, [field]: event.target.value })}
            />
          </Field>
        ))}
        {changes === null && <p className="login__insecure">{t('diag.policyEdit.wholeNumbers')}</p>}
        <p className="muted small">{t('diag.policyEdit.existing')}</p>
      </div>
    </Modal>
  )
}
