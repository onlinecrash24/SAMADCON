/**
 * Unix/Scripts/Startup — scripts a Linux member runs at boot.
 *
 * Like Unix/Files, an entry names a file that has to be on SYSVOL already, so
 * the script is picked from what is there rather than typed. Unlike it, the
 * manifest carries a digest of that file, and the digest is what decides
 * whether a member re-runs the script after it changes. Nobody types that
 * either: the server computes it from the bytes on the share when the policy
 * is saved, which is why replacing a script and saving without touching a
 * single field is a real change.
 *
 * `run_once` is a checkbox because the format makes it one — the element
 * carries no text, and having it is the whole statement. Ticked, the script
 * runs on the next refresh and leaves nothing behind to undo; unticked, it
 * becomes an `@reboot` line in /etc/cron.d on the member.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'

import { api } from '../../../api/endpoints'
import type { Gpo, VgpEntry } from '../../../api/types'
import { ErrorMessage } from '../../../components/primitives'
import { useI18n } from '../../../i18n'

// root is what the extension substitutes for an absent run_as, so it is the
// honest default rather than an empty box.
const BLANK: VgpEntry = { script: '', parameters: '', run_as: 'root', run_once: false }

export function StartupEditor({
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
    queryKey: ['vgp-payloads', gpo.dn, 'startup'],
    queryFn: () => api.vgpPayloads(gpo.dn, 'startup'),
  })

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadVgpPayload(gpo.dn, 'startup', file),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['vgp-payloads', gpo.dn, 'startup'] }),
    onError: setError,
  })

  const available = payloads.data?.payloads ?? []
  const edit = (index: number, key: string, value: unknown) =>
    onChange(entries.map((entry, at) => (at === index ? { ...entry, [key]: value } : entry)))

  return (
    <div className="stack-tight">
      <ErrorMessage error={error} onDismiss={() => setError(null)} />

      <p className="muted small">{t('vgp.startupHint')}</p>

      <div className="table-wrap">
        <table className="table table--compact">
          <thead>
            <tr>
              <th>{t('vgp.field.script')}</th>
              <th>{t('vgp.field.parameters')}</th>
              <th className="table__cell--account">{t('vgp.field.runAs')}</th>
              <th className="table__cell--narrow">{t('vgp.field.runOnce')}</th>
              <th className="table__cell--narrow" />
            </tr>
          </thead>
          <tbody>
            {entries.map((entry, index) => (
              <tr key={index}>
                <td>
                  {/* Picked, not typed: the script has to be on the share
                      already, and the server refuses anything else. */}
                  <select
                    value={String(entry.script ?? '')}
                    onChange={(event) => edit(index, 'script', event.target.value)}
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
                    value={String(entry.parameters ?? '')}
                    placeholder="--quiet"
                    onChange={(event) => edit(index, 'parameters', event.target.value)}
                  />
                </td>
                <td className="table__cell--account">
                  <input
                    value={String(entry.run_as ?? '')}
                    onChange={(event) => edit(index, 'run_as', event.target.value)}
                  />
                </td>
                <td className="table__cell--narrow">
                  <input
                    type="checkbox"
                    checked={Boolean(entry.run_once)}
                    aria-label={t('vgp.field.runOnce')}
                    onChange={(event) => edit(index, 'run_once', event.target.checked)}
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="button button--danger"
                    onClick={() => onChange(entries.filter((_, at) => at !== index))}
                  >
                    {t('action.remove')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {entries.length === 0 && <p className="muted">{t('vgp.none')}</p>}

      <div className="pane__actions">
        <button
          type="button"
          className="button"
          onClick={() => onChange([...entries, { ...BLANK }])}
        >
          + {t('vgp.add')}
        </button>
        <button
          type="button"
          className="button"
          disabled={upload.isPending}
          onClick={() => picker.current?.click()}
        >
          {upload.isPending ? t('status.loading') : t('vgp.uploadScript')}
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
    </div>
  )
}
