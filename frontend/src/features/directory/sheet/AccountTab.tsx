import { useState } from 'react'

import type { UserDetail } from '../../../api/types'
import { Badge, Field, TextRow, useDateFormat } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import type { MessageKey } from '../../../i18n/messages'
import {
  AES128,
  AES256,
  ENCRYPTION_ATTRIBUTE,
  hasEncryption,
  withEncryption,
} from '../encryptionTypes'
import { ACCOUNT_FLAGS, DANGEROUS_FLAGS, FIELDS } from '../fieldDefs'
import { bothSet, choosePasswordOption, type PasswordOption } from '../passwordOptions'
import { toDateInput, withRawAttribute } from './draft'
import { FieldInput } from './FieldInput'
import { useSheet } from './SheetContext'

/** ADUC's two AES boxes, in its order, after the other account options. */
const AES_OPTIONS = [
  { bit: AES128, label: 'user.aes128' },
  { bit: AES256, label: 'user.aes256' },
] as const

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
  const options = { mustChange, neverExpires: flag('password_never_expires') }
  // In the ACL rather than userAccountControl; null when it could not be read.
  const cannotKnown = user.status.cannot_change_password != null
  const cannotChange = draft.cannotChangePassword ?? user.status.cannot_change_password ?? false
  // Which box the last tick cleared, to say why it moved — ADUC says it in a
  // message box; here it is a line under the options.
  const [cleared, setCleared] = useState<PasswordOption | null>(null)

  // The AES boxes are two bits of one attribute; the edit goes through the
  // attribute editor's part of the draft, against what the directory said.
  const savedEncryption = user.supported_encryption_types ?? null
  const queuedEncryption = draft.raw[ENCRYPTION_ATTRIBUTE]
  const encryption = queuedEncryption
    ? queuedEncryption.after.length
      ? Number(queuedEncryption.after[0])
      : null
    : savedEncryption
  const setEncryption = (bit: number, on: boolean) => {
    const next = withEncryption(encryption, bit, on)
    const asList = (value: number | null) => (value === null ? [] : [String(value)])
    setDraft((d) => withRawAttribute(d, ENCRYPTION_ATTRIBUTE, asList(savedEncryption), asList(next)))
  }

  const choose = (which: PasswordOption, value: boolean) => {
    const { next, cleared: other } = choosePasswordOption(options, which, value)
    setCleared(other)
    setDraft((d) => ({
      ...d,
      mustChangePassword: next.mustChange,
      flags: { ...d.flags, password_never_expires: next.neverExpires },
    }))
  }

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
            onChange={(event) => choose('mustChange', event.target.checked)}
          />
          <span>{t('dialog.passwordMustChange')}</span>
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={cannotChange}
            disabled={busy || !cannotKnown}
            onChange={(event) => setDraft((d) => ({ ...d, cannotChangePassword: event.target.checked }))}
          />
          <span>
            {t('user.cannotChangePassword')}
            {!cannotKnown && <span className="muted small"> — {t('user.cannotChangeUnknown')}</span>}
          </span>
        </label>
        {ACCOUNT_FLAGS.filter((name) => name in user.flags).map((name) => (
          <label className="checkbox" key={name}>
            <input
              type="checkbox"
              checked={flag(name)}
              disabled={busy}
              onChange={(event) =>
                name === 'password_never_expires'
                  ? choose('neverExpires', event.target.checked)
                  : setFlag(name, event.target.checked)
              }
            />
            <span>
              {t(`flag.${name}` as MessageKey)}
              {DANGEROUS_FLAGS.has(name) && flag(name) && (
                <Badge tone="danger">{t('flag.dangerous')}</Badge>
              )}
            </span>
          </label>
        ))}
        {AES_OPTIONS.map(({ bit, label }) => (
          <label className="checkbox" key={label}>
            <input
              type="checkbox"
              checked={hasEncryption(encryption, bit)}
              disabled={busy}
              onChange={(event) => setEncryption(bit, event.target.checked)}
            />
            <span>{t(label)}</span>
          </label>
        ))}
        {cleared && (
          <p className="muted small">
            {t(cleared === 'mustChange' ? 'user.clearedMustChange' : 'user.clearedNeverExpires')}
          </p>
        )}
        {bothSet(options) && <div className="alert alert--warning">{t('user.passwordOptionsBoth')}</div>}
        {mustChange && cannotChange && (
          // ADUC lets both stay ticked and refuses on OK; this says so before.
          <div className="alert alert--warning">{t('user.mustAndCannot')}</div>
        )}
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
