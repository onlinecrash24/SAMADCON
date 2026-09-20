import type { UserDetail } from '../../../api/types'
import { Badge, Field, TextRow, useDateFormat } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import type { MessageKey } from '../../../i18n/messages'
import { ACCOUNT_FLAGS, DANGEROUS_FLAGS, FIELDS } from '../fieldDefs'
import { toDateInput } from './draft'
import { FieldInput } from './FieldInput'
import { useSheet } from './SheetContext'

/**
 * ADUC's Account tab: the logon name, the account options, when it expires.
 *
 * Every control here writes to the draft and nothing else. This tab used to
 * be the worst offender: the account options waited for a Save button while
 * "must change password" and the expiry each wrote the moment they were
 * touched — three rules on one screen. Now there is one, and it is the
 * footer's.
 */
export function AccountTab({ user }: { user: UserDetail }) {
  const { t } = useI18n()
  const formatDate = useDateFormat()
  const { draft, setDraft, flag, setFlag, busy } = useSheet()

  const expiry = draft.accountExpires ?? toDateInput(user.status.account_expires)
  const never = expiry === ''
  const mustChange = draft.mustChangePassword ?? user.status.must_change_password

  return (
    <>
      <FieldInput field={FIELDS.upn} />
      <TextRow label={t('user.samName')} value={user.sam_account_name} />
      <FieldInput field={FIELDS.logon_workstations} />

      {user.status.locked_out && (
        <label className="checkbox">
          <input
            type="checkbox"
            checked={draft.unlock ?? false}
            disabled={busy}
            onChange={(event) => setDraft((d) => ({ ...d, unlock: event.target.checked }))}
          />
          <span>
            {t('user.unlockAccount')}
            <Badge tone="warn">{t('user.status.lockedOut')}</Badge>
          </span>
        </label>
      )}

      <fieldset className="radio-group radio-group--block">
        <legend>{t('detail.accountOptions')}</legend>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={mustChange}
            disabled={busy}
            onChange={(event) => setDraft((d) => ({ ...d, mustChangePassword: event.target.checked }))}
          />
          <span>{t('dialog.passwordMustChange')}</span>
        </label>
        {ACCOUNT_FLAGS.filter((name) => name in user.flags).map((name) => (
          <label className="checkbox" key={name}>
            <input
              type="checkbox"
              checked={flag(name)}
              disabled={busy}
              onChange={(event) => setFlag(name, event.target.checked)}
            />
            <span>
              {t(`flag.${name}` as MessageKey)}
              {DANGEROUS_FLAGS.has(name) && flag(name) && (
                <Badge tone="danger">{t('flag.dangerous')}</Badge>
              )}
            </span>
          </label>
        ))}
      </fieldset>

      <fieldset className="radio-group radio-group--block">
        <legend>{t('user.accountExpires')}</legend>
        <label className="checkbox">
          <input
            type="radio"
            name="expires"
            checked={never}
            disabled={busy}
            onChange={() => setDraft((d) => ({ ...d, accountExpires: '' }))}
          />
          <span>{t('user.expiresNever')}</span>
        </label>
        <label className="checkbox">
          <input
            type="radio"
            name="expires"
            checked={!never}
            disabled={busy}
            onChange={() =>
              setDraft((d) => ({
                ...d,
                accountExpires: expiry || new Date().toISOString().slice(0, 10),
              }))
            }
          />
          <span>{t('user.expiresOn')}</span>
          <input
            type="date"
            value={expiry}
            disabled={busy || never}
            onChange={(event) => setDraft((d) => ({ ...d, accountExpires: event.target.value }))}
            style={{ width: 'auto' }}
          />
        </label>
      </fieldset>

      <Field label={t('user.passwordLastSet')}>
        <span className="muted">{formatDate(user.status.password_last_set) || '—'}</span>
      </Field>
    </>
  )
}
