/**
 * Folder redirection — user configuration only, there is no computer half.
 *
 * One row per folder Windows lets you redirect, whether or not this policy
 * touches it: the question people arrive with is "is Documents redirected",
 * and a list of only the configured ones answers it by omission, which is the
 * weaker answer.
 *
 * The target group is Everyone by default, which is what GPMC's *Basic*
 * redirection writes. Per-group targets exist in the file and are shown, but
 * setting them up is GPMC's *Advanced* mode and not offered here.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { api } from '../../../api/endpoints'
import type { Gpo, RedirectedFolder } from '../../../api/types'
import { ErrorMessage, Spinner } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import type { MessageKey } from '../../../i18n/messages'

/** What GPMC's basic redirection writes: everyone the policy reaches. */
const EVERYONE = 'S-1-1-0'

export function RedirectionTab({
  gpo,
  onChanged,
}: {
  gpo: Gpo
  onChanged: (message: string) => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const [draft, setDraft] = useState<Record<string, string>>({})
  const [error, setError] = useState<unknown>(null)

  const known = useQuery({ queryKey: ['known-folders'], queryFn: () => api.knownFolders() })
  const current = useQuery({
    queryKey: ['gpo-redirection', gpo.dn],
    queryFn: () => api.gpoRedirection(gpo.dn),
  })

  // Refilled from the answer: the form edits a copy so a half-typed path is
  // never mistaken for what the policy says.
  useEffect(() => {
    const paths: Record<string, string> = {}
    for (const folder of current.data?.folders ?? []) {
      const everyone = folder.targets.find((item) => item.sid.toLowerCase() === EVERYONE.toLowerCase())
      paths[folder.guid] = (everyone ?? folder.targets[0])?.path ?? ''
    }
    setDraft(paths)
  }, [current.data])

  const save = useMutation({
    mutationFn: ({ guid, path }: { guid: string; path: string | null }) =>
      api.redirectFolder(gpo.dn, {
        folder: guid,
        sid: EVERYONE,
        path,
        expected_version: current.data?.version_number,
      }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['gpo-redirection', gpo.dn] })
      onChanged(result.changed ? t('redirection.saved') : t('redirection.unchanged'))
    },
    onError: setError,
  })

  if (known.isLoading || current.isLoading) return <Spinner label={t('status.loading')} />
  if (known.error) return <ErrorMessage error={known.error} />
  if (current.error) return <ErrorMessage error={current.error} />

  const configured = new Map(
    (current.data?.folders ?? []).map((folder) => [folder.guid, folder]),
  )

  // Anything the file names that Windows' table does not — shown by its id
  // rather than dropped, because a redirection we cannot label is still one
  // that applies.
  const extra = (current.data?.folders ?? []).filter(
    (folder) => !(known.data?.folders ?? []).some((item) => item.guid === folder.guid),
  )

  const rows = [
    ...(known.data?.folders ?? []).map((item) => ({ guid: item.guid, name: item.name })),
    ...extra.map((folder) => ({ guid: folder.guid, name: '' })),
  ]

  return (
    <div className="stack-tight">
      <ErrorMessage error={error} onDismiss={() => setError(null)} />

      {current.data?.folders.length ? null : (
        <p className="muted small">{t('redirection.hint')}</p>
      )}

      {/* The same trap as the scripts tab: written, but applied by nobody. */}
      {!current.data?.registered && (current.data?.folders.length ?? 0) > 0 && (
        <div className="alert alert--warning">{t('redirection.notRegistered')}</div>
      )}

      <div className="table-wrap">
        <table className="table table--compact">
          <thead>
            <tr>
              <th className="table__cell--folder">{t('redirection.folder')}</th>
              <th>{t('redirection.target')}</th>
              <th className="table__cell--narrow" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const folder = configured.get(row.guid)
              const value = draft[row.guid] ?? ''
              const saved = folder ? targetPath(folder) : ''
              return (
                <tr key={row.guid}>
                  <td>
                    <strong>{row.name ? t(`redirection.name.${row.name}` as MessageKey) : row.guid}</strong>
                    {row.name && <div className="muted small mono">{row.guid}</div>}
                  </td>
                  <td>
                    <input
                      value={value}
                      placeholder={t('redirection.notRedirected')}
                      onChange={(event) =>
                        setDraft({ ...draft, [row.guid]: event.target.value })
                      }
                    />
                  </td>
                  <td>
                    <div className="pane__actions">
                      <button
                        type="button"
                        className="button"
                        disabled={save.isPending || value.trim() === saved}
                        onClick={() =>
                          save.mutate({ guid: row.guid, path: value.trim() || null })
                        }
                      >
                        {t('action.save')}
                      </button>
                      {folder && (
                        <button
                          type="button"
                          className="button button--danger"
                          disabled={save.isPending}
                          onClick={() => save.mutate({ guid: row.guid, path: null })}
                        >
                          {t('redirection.clear')}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="muted small">{t('redirection.everyoneHint')}</p>
    </div>
  )
}

function targetPath(folder: RedirectedFolder): string {
  const everyone = folder.targets.find((item) => item.sid.toLowerCase() === EVERYONE.toLowerCase())
  return (everyone ?? folder.targets[0])?.path ?? ''
}
