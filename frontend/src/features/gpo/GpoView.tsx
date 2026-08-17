/**
 * Group policy management.
 *
 * The list on the left of GPMC answers "what policies exist"; the questions
 * people actually have are "where does this one apply" and "what reaches this
 * OU". Both are one click from the list here rather than two trees apart.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import type { Gpo } from '../../api/types'
import { Badge, ErrorMessage, Modal, Spinner, useDateFormat } from '../../components/primitives'
import { useI18n } from '../../i18n'
import { GpoDetail } from './GpoDetail'

interface GpoViewProps {
  onChanged: (message: string) => void
}

export function GpoView({ onChanged }: GpoViewProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const formatDate = useDateFormat()

  const [selected, setSelected] = useState<Gpo | null>(null)
  const [creating, setCreating] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const listing = useQuery({ queryKey: ['gpos'], queryFn: () => api.gpos() })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['gpos'] })
  }

  if (listing.isLoading) return <Spinner label={t('status.loading')} />
  if (listing.error) return <ErrorMessage error={listing.error} />

  const gpos = listing.data?.gpos ?? []

  return (
    <>
      <div className="pane__header">
        <span className="muted small">{t('gpo.count', { count: gpos.length })}</span>
        <div className="pane__actions">
          <button type="button" className="button" onClick={() => setCreating(true)}>
            + {t('gpo.newGpo')}
          </button>
          <button type="button" className="button" onClick={() => setRestoring(true)}>
            {t('gpo.restore')}
          </button>
        </div>
      </div>

      <ErrorMessage error={error} onDismiss={() => setError(null)} />

      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>{t('gpo.name')}</th>
              <th>{t('gpo.version')}</th>
              <th>{t('gpo.contents')}</th>
              <th>{t('gpo.changed')}</th>
            </tr>
          </thead>
          <tbody>
            {gpos.map((gpo) => (
              <tr
                key={gpo.dn}
                className={selected?.dn === gpo.dn ? 'table__row--selected' : undefined}
                onClick={() => setSelected(gpo)}
              >
                <td>
                  <button type="button" className="link" onClick={() => setSelected(gpo)}>
                    {gpo.display_name ?? gpo.guid}
                  </button>
                  <div className="muted small mono">{gpo.guid}</div>
                </td>
                <td className="small">
                  {t('gpo.versionPair', {
                    machine: gpo.machine_version,
                    user: gpo.user_version,
                  })}
                </td>
                <td>
                  <GpoHalves gpo={gpo} />
                </td>
                <td className="muted small">{formatDate(gpo.changed)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && (
        <GpoDetail
          gpo={selected}
          onClose={() => setSelected(null)}
          onChanged={(message) => {
            refresh()
            onChanged(message)
          }}
          onDeleted={() => {
            setSelected(null)
            refresh()
            onChanged(t('gpo.deleted'))
          }}
        />
      )}

      {creating && (
        <NewGpoDialog
          onClose={() => setCreating(false)}
          onDone={() => {
            setCreating(false)
            refresh()
            onChanged(t('gpo.createdNotice'))
          }}
        />
      )}

      {restoring && (
        <RestoreDialog
          onClose={() => setRestoring(false)}
          onDone={() => {
            setRestoring(false)
            refresh()
            onChanged(t('gpo.restored'))
          }}
        />
      )}
    </>
  )
}

/**
 * Restore from a backup archive.
 *
 * Always creates a new policy. Restoring onto the original would discard
 * whatever has happened to it since, and its identifier is what every link in
 * the domain points at — that is not an operation to offer behind one button.
 */
function RestoreDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { t } = useI18n()
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [error, setError] = useState<unknown>(null)

  const restore = useMutation({
    mutationFn: () => api.restoreGpo(file!, name.trim() || undefined),
    onSuccess: onDone,
    onError: setError,
  })

  return (
    <Modal
      title={t('gpo.restore')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={!file || restore.isPending}
            onClick={() => restore.mutate()}
          >
            {t('gpo.restore')}
          </button>
        </>
      }
    >
      <ErrorMessage error={error} />
      <label className="field">
        <span className="field__label">{t('gpo.backupFile')}</span>
        <input
          type="file"
          accept=".zip,application/zip"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <span className="field__hint">{t('gpo.restoreHint')}</span>
      </label>
      <label className="field">
        <span className="field__label">{t('gpo.name')}</span>
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={t('gpo.nameFromBackup')}
        />
      </label>
    </Modal>
  )
}

/**
 * Which halves of a policy have a client-side extension registered, and which
 * are switched off.
 *
 * Registered is not the same as configured, and the badge used to claim it
 * was: a half stays green after its last setting is removed, because the
 * extension registration survives. That is deliberate — a client learns to
 * remove a value it applied earlier by running the extension and finding the
 * value gone, so unregistering would strand it. The colour therefore answers
 * "does anything run for this half", and the tooltip says so; whether it finds
 * anything to do is what the settings report answers.
 */
function GpoHalves({ gpo }: { gpo: Gpo }) {
  const { t } = useI18n()

  const tone = (registered: boolean, enabled: boolean) =>
    !enabled ? 'warn' : registered ? 'ok' : 'muted'

  const title = (registered: boolean, enabled: boolean) =>
    !enabled
      ? t('gpo.halfOff')
      : registered
        ? t('gpo.halfRegistered')
        : t('gpo.halfNothing')

  return (
    <div className="badge-row">
      <span title={title(Boolean(gpo.machine_extensions), gpo.machine_enabled)}>
        <Badge tone={tone(Boolean(gpo.machine_extensions), gpo.machine_enabled)}>
          {t('gpo.machine')}
          {!gpo.machine_enabled && ` (${t('gpo.off')})`}
        </Badge>
      </span>
      <span title={title(Boolean(gpo.user_extensions), gpo.user_enabled)}>
        <Badge tone={tone(Boolean(gpo.user_extensions), gpo.user_enabled)}>
          {t('gpo.user')}
          {!gpo.user_enabled && ` (${t('gpo.off')})`}
        </Badge>
      </span>
    </div>
  )
}

function NewGpoDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { t } = useI18n()
  const [name, setName] = useState('')
  const [error, setError] = useState<unknown>(null)

  const create = useMutation({
    mutationFn: () => api.createGpo(name.trim()),
    onSuccess: onDone,
    onError: setError,
  })

  return (
    <Modal
      title={t('gpo.newGpo')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={!name.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            {t('action.create')}
          </button>
        </>
      }
    >
      <ErrorMessage error={error} />
      <label className="field">
        <span className="field__label">{t('gpo.name')}</span>
        <input value={name} onChange={(event) => setName(event.target.value)} autoFocus />
        <span className="field__hint">{t('gpo.newHint')}</span>
      </label>
    </Modal>
  )
}

