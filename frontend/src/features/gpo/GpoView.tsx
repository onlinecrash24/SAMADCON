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
  /** The container the tree points at; null is every policy, as before. */
  containerDn: string | null
  onChanged: (message: string) => void
}

export function GpoView({ containerDn, onChanged }: GpoViewProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const formatDate = useDateFormat()

  const [selected, setSelected] = useState<Gpo | null>(null)
  const [creating, setCreating] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const listing = useQuery({ queryKey: ['gpos'], queryFn: () => api.gpos() })

  // The same key the tree uses, so picking a container costs no second call.
  const linkMap = useQuery({
    queryKey: ['gpo-link-map'],
    queryFn: () => api.gpoLinkMap(),
    staleTime: 30_000,
    enabled: containerDn !== null,
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['gpos'] })
  }

  if (listing.isLoading) return <Spinner label={t('status.loading')} />
  if (listing.error) return <ErrorMessage error={listing.error} />

  const all = listing.data?.gpos ?? []

  // With a container picked, the list answers "what applies here" and in the
  // order it applies — precedence, not the alphabet. Without one it is every
  // policy, which is what this console showed before there was a tree.
  const linkedHere = containerDn
    ? (linkMap.data?.containers ?? []).find(
        (node) => node.dn.toLowerCase() === containerDn.toLowerCase(),
      )
    : undefined

  const gpos = containerDn
    ? (linkedHere?.links ?? [])
        .map((link) => all.find((gpo) => gpo.guid.toUpperCase() === link.guid.toUpperCase()))
        // A link can outlive its policy. The tree says so in its own row; here
        // there is no policy to draw, so the row simply is not there.
        .filter((gpo): gpo is Gpo => gpo !== undefined)
    : all

  return (
    <>
      <div className="pane__header">
        <span className="muted small">
          {containerDn
            ? t('gpo.countLinked', { count: gpos.length, container: linkedHere?.name ?? '' })
            : t('gpo.count', { count: gpos.length })}
        </span>
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
 * Which halves of a policy carry anything, and which are switched off.
 *
 * A half whose last setting is removed is unregistered again, so grey here
 * really does mean empty. That took a GPMC reference to settle: the reasoning
 * said the registration had to stay, because a client clears a value it
 * applied earlier by running the extension and finding the value gone. GPMC
 * disagrees, and GPMC is the specification.
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

