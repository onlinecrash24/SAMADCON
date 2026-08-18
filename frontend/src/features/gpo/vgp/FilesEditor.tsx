/**
 * Unix/Files — the one Samba policy whose entries name a file instead of
 * carrying their content.
 *
 * That shapes the editor. The file has to be on SYSVOL before an entry can
 * refer to it, so uploading comes first and the source is picked from what is
 * there rather than typed: a name that is not on the share is refused by the
 * server anyway, and a list makes the constraint visible instead of leaving it
 * to be discovered.
 *
 * Two things the format allows and nobody means, both warned about here
 * because neither shows up as an error anywhere else:
 *
 *   * Mode 0000. Samba's `calc_mode` starts at zero and only ever ORs, so an
 *     entry without permissions describes a file no one may read. It writes
 *     and applies without complaint.
 *   * A user or group that does not exist on the member. The applier resolves
 *     them with getpwnam/getgrnam and throws; the policy is formally correct
 *     and does nothing.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'

import { api } from '../../../api/endpoints'
import type { Gpo, VgpEntry } from '../../../api/types'
import { ErrorMessage } from '../../../components/primitives'
import { useI18n } from '../../../i18n'

/** A mode as `rw-r--r--`, or a dash when the text is not an octal mode. */
export function symbolic(mode: string): string {
  const value = Number.parseInt(mode, 8)
  if (!Number.isInteger(value) || value < 0 || value > 0o777) return '—'

  const letters = ['r', 'w', 'x']
  let out = ''
  for (let shift = 6; shift >= 0; shift -= 3) {
    for (let index = 0; index < 3; index += 1) {
      const bit = (0o4 >> index) << shift
      out += (value & bit) === 0 ? '-' : letters[index]
    }
  }
  return out
}

export function grantsNothing(mode: string): boolean {
  return Number.parseInt(mode, 8) === 0
}

const BLANK: VgpEntry = { source: '', target: '', user: 'root', group: 'root', mode: '0644' }

export function FilesEditor({
  gpo,
  entries,
  onChange,
}: {
  gpo: Gpo
  entries: VgpEntry[]
  onChange: (entries: VgpEntry[]) => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [error, setError] = useState<unknown>(null)
  const picker = useRef<HTMLInputElement>(null)

  const payloads = useQuery({
    queryKey: ['vgp-payloads', gpo.dn],
    queryFn: () => api.vgpPayloads(gpo.dn, 'files'),
  })

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadVgpPayload(gpo.dn, 'files', file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['vgp-payloads', gpo.dn] }),
    onError: setError,
  })

  const available = payloads.data?.payloads ?? []
  const edit = (index: number, key: string, value: unknown) =>
    onChange(entries.map((entry, at) => (at === index ? { ...entry, [key]: value } : entry)))

  return (
    <div className="stack-tight">
      <ErrorMessage error={error} onDismiss={() => setError(null)} />

      <p className="muted small">{t('vgp.filesHint')}</p>

      <div className="table-wrap">
        <table className="table table--compact">
          <thead>
            <tr>
              <th>{t('vgp.field.source')}</th>
              <th>{t('vgp.field.target')}</th>
              <th className="table__cell--account">{t('vgp.field.user')}</th>
              <th className="table__cell--account">{t('vgp.field.group')}</th>
              <th className="table__cell--mode">{t('vgp.field.mode')}</th>
              <th className="table__cell--narrow" />
            </tr>
          </thead>
          <tbody>
            {entries.map((entry, index) => {
              const mode = String(entry.mode ?? '')
              return (
                <tr key={index}>
                  <td>
                    {/* Picked, not typed: the file has to be on the share
                        already, and the server refuses anything else. */}
                    <select
                      value={String(entry.source ?? '')}
                      onChange={(event) => edit(index, 'source', event.target.value)}
                    >
                      <option value="">{t('vgp.pickFile')}</option>
                      {available.map((file) => (
                        <option key={file.name} value={file.name}>
                          {file.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      value={String(entry.target ?? '')}
                      placeholder="/etc/example.conf"
                      onChange={(event) => edit(index, 'target', event.target.value)}
                    />
                  </td>
                  <td className="table__cell--account">
                    <input
                      value={String(entry.user ?? '')}
                      onChange={(event) => edit(index, 'user', event.target.value)}
                    />
                  </td>
                  <td className="table__cell--account">
                    <input
                      value={String(entry.group ?? '')}
                      onChange={(event) => edit(index, 'group', event.target.value)}
                    />
                  </td>
                  <td className="table__cell--mode">
                    <span className="mode">
                      <input
                        className="mono"
                        value={mode}
                        placeholder="0644"
                        onChange={(event) => edit(index, 'mode', event.target.value)}
                      />
                      <span className="mono small muted">{symbolic(mode)}</span>
                    </span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="link"
                      onClick={() => onChange(entries.filter((_, at) => at !== index))}
                    >
                      {t('action.remove')}
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {entries.some((entry) => grantsNothing(String(entry.mode ?? ''))) && (
        <div className="alert alert--warning">{t('vgp.modeGrantsNothing')}</div>
      )}

      <div className="pane__actions">
        <button type="button" className="button" onClick={() => onChange([...entries, BLANK])}>
          + {t('vgp.add')}
        </button>
        <button
          type="button"
          className="button"
          disabled={upload.isPending}
          onClick={() => picker.current?.click()}
        >
          {upload.isPending ? t('status.loading') : t('vgp.uploadFile')}
        </button>
        <input
          ref={picker}
          type="file"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0]
            // Cleared so the same file can be picked twice in a row — after a
            // failed upload that is exactly what someone tries.
            event.target.value = ''
            if (file) upload.mutate(file)
          }}
        />
      </div>

      <p className="muted small">
        {available.length === 0
          ? t('vgp.noFilesYet')
          : t('vgp.filesOnShare', {
              names: available.map((file) => file.name).join(', '),
            })}
      </p>
    </div>
  )
}
