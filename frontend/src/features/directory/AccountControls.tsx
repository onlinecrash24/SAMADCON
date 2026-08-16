/**
 * Account settings that are not plain attributes.
 *
 * Expiry and "must change password at next logon" each have their own
 * endpoint, because Active Directory stores them in ways a text field cannot
 * express: accountExpires is a FILETIME with two different encodings for
 * "never", and pwdLastSet only accepts 0 or -1.
 */

import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import { ErrorMessage, Field } from '../../components/primitives'
import { useI18n } from '../../i18n'
import type { UserDetail } from '../../api/types'

interface AccountControlsProps {
  user: UserDetail
  onChanged: (message: string) => void
}

/** ISO timestamp → yyyy-mm-dd for <input type="date">, or '' when unset. */
function toDateInput(value: string | null): string {
  if (!value) return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toISOString().slice(0, 10)
}

export function AccountControls({ user, onChanged }: AccountControlsProps) {
  const { t } = useI18n()
  const [expiry, setExpiry] = useState(() => toDateInput(user.status.account_expires))
  const [error, setError] = useState<unknown>(null)

  const saveExpiry = useMutation({
    mutationFn: (value: string) =>
      // The account expires at the end of the chosen day, which is what an
      // administrator means by "expires on the 5th".
      api.setExpiry(user.dn, value ? new Date(`${value}T23:59:59Z`).toISOString() : null),
    onSuccess: () => {
      setError(null)
      onChanged(t('status.saved'))
    },
    onError: setError,
  })

  const mustChange = useMutation({
    mutationFn: (value: boolean) => api.setMustChangePassword(user.dn, value),
    onSuccess: () => {
      setError(null)
      onChanged(t('status.saved'))
    },
    onError: setError,
  })

  const changed = expiry !== toDateInput(user.status.account_expires)

  return (
    <section className="detail__section">
      <h3>{t('detail.account')}</h3>
      <ErrorMessage error={error} onDismiss={() => setError(null)} />

      <Field label={t('user.accountExpires')} hint={t('user.expiryHint')}>
        <div className="login__server">
          <input
            type="date"
            value={expiry}
            onChange={(event) => setExpiry(event.target.value)}
          />
          <button
            type="button"
            className="button"
            disabled={!changed || saveExpiry.isPending}
            onClick={() => saveExpiry.mutate(expiry)}
          >
            {t('action.save')}
          </button>
        </div>
      </Field>

      <label className="checkbox">
        <input
          type="checkbox"
          checked={user.status.must_change_password}
          disabled={mustChange.isPending}
          onChange={(event) => mustChange.mutate(event.target.checked)}
        />
        <span>{t('dialog.passwordMustChange')}</span>
      </label>
    </section>
  )
}
