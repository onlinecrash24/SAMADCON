/**
 * BitLocker recovery keys: the list on a computer, and the search by key ID.
 *
 * The list never carries a password. Each one is fetched on its own by a POST
 * that the server records in the audit log — the same rule as LAPS — and it
 * lives in this component's state only, never in the query cache.
 */

import { useMutation, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { api } from '../../api/endpoints'
import type { BitlockerKey } from '../../api/types'
import {
  CopyButton,
  ErrorMessage,
  Field,
  Modal,
  Spinner,
  useDateFormat,
} from '../../components/primitives'
import { useI18n } from '../../i18n'

/** One key: its ID and date, and the password once someone asks for it. */
function KeyRow({
  computerDn,
  entry,
  computer,
}: {
  computerDn: string
  entry: BitlockerKey
  computer?: string
}) {
  const { t } = useI18n()
  const formatDate = useDateFormat()
  const [password, setPassword] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)

  const reveal = useMutation({
    mutationFn: () => api.revealBitlockerKey(computerDn, entry.key_id),
    onSuccess: (result) => {
      setError(null)
      setPassword(result.recovery_password)
    },
    onError: setError,
  })

  return (
    <li className="bitlocker__key">
      <div className="bitlocker__meta">
        {computer && <strong>{computer}</strong>}
        <span className="mono" title={entry.key_id}>
          {entry.key_id_short}
        </span>
        <span className="muted small">{formatDate(entry.created)}</span>
      </div>
      {password ? (
        <div className="bitlocker__secret">
          <span className="mono selectable">{password}</span>
          <CopyButton value={password} />
        </div>
      ) : (
        <button
          type="button"
          className="button"
          disabled={reveal.isPending}
          onClick={() => reveal.mutate()}
        >
          {t('computer.lapsReveal')}
        </button>
      )}
      <ErrorMessage error={error} onDismiss={() => setError(null)} />
    </li>
  )
}

/** The block in a computer's detail pane, under LAPS. */
export function BitlockerKeys({ computerDn }: { computerDn: string }) {
  const { t } = useI18n()
  const listing = useQuery({
    queryKey: ['bitlocker', computerDn],
    queryFn: () => api.bitlockerKeys(computerDn),
  })

  return (
    <>
      <h3>{t('computer.bitlocker')}</h3>
      {listing.isPending ? (
        <Spinner />
      ) : listing.error ? (
        <ErrorMessage error={listing.error} />
      ) : !listing.data.available ? (
        <p className="muted">{t('computer.bitlockerNoSchema')}</p>
      ) : listing.data.keys.length === 0 ? (
        <p className="muted">{t('computer.bitlockerNone')}</p>
      ) : (
        <>
          <ul className="bitlocker">
            {listing.data.keys.map((entry) => (
              <KeyRow key={entry.key_id} computerDn={computerDn} entry={entry} />
            ))}
          </ul>
          <p className="muted small">{t('computer.lapsWarning')}</p>
        </>
      )}
    </>
  )
}

/** "Find BitLocker recovery password", from the domain's menu, as in ADUC. */
export function FindBitlockerDialog({ onClose }: { onClose: () => void }) {
  const { t } = useI18n()
  const [keyId, setKeyId] = useState('')
  const search = useMutation({ mutationFn: (value: string) => api.findBitlockerKey(value) })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    search.mutate(keyId.trim())
  }

  return (
    <Modal
      title={t('bitlocker.findTitle')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.close')}
          </button>
          <button
            type="submit"
            form="find-bitlocker"
            className="button button--primary"
            disabled={search.isPending || keyId.trim().length < 8}
          >
            {t('bitlocker.find')}
          </button>
        </>
      }
    >
      <form id="find-bitlocker" onSubmit={submit} className="form">
        <Field label={t('bitlocker.keyId')} hint={t('bitlocker.keyIdHint')}>
          <input
            autoFocus
            className="mono"
            maxLength={38}
            spellCheck={false}
            autoComplete="off"
            value={keyId}
            onChange={(event) => setKeyId(event.target.value)}
          />
        </Field>
        <ErrorMessage error={search.error} onDismiss={() => search.reset()} />
        {search.data &&
          (search.data.keys.length === 0 ? (
            <p className="muted">{t('bitlocker.noMatch')}</p>
          ) : (
            <>
              <ul className="bitlocker">
                {search.data.keys.map((entry) => (
                  <KeyRow
                    key={entry.dn}
                    computerDn={entry.computer_dn}
                    entry={entry}
                    computer={entry.computer}
                  />
                ))}
              </ul>
              <p className="muted small">{t('computer.lapsWarning')}</p>
            </>
          ))}
      </form>
    </Modal>
  )
}
