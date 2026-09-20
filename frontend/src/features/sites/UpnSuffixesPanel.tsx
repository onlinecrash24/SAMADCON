import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { api } from '../../api/endpoints'
import { ErrorMessage, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'

/**
 * The forest's UPN suffixes — RSAT keeps these behind Domains and Trusts →
 * Properties → UPN Suffixes, a console this does not have, so they sit here
 * with the rest of the forest's configuration.
 *
 * Two lists drawn as one. The forest's domains are suffixes by nature and
 * cannot be removed; the ones added by hand can. Edits gather in a draft and
 * go to the directory on Save as one replace — the way the sheet works, and
 * for the same reason: a suffix half-typed and already written is a logon
 * name nobody can use.
 */
export function UpnSuffixesPanel({ onChanged }: { onChanged: (message: string) => void }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const listing = useQuery({ queryKey: ['upn-management'], queryFn: () => api.upnSuffixDescription() })

  // null until someone edits: the list shown is then the directory's own.
  const [draft, setDraft] = useState<string[] | null>(null)
  const [entry, setEntry] = useState('')
  const [error, setError] = useState<unknown>(null)

  const added = draft ?? listing.data?.added ?? []
  const domains = listing.data?.domains ?? []
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(listing.data?.added ?? [])

  const save = useMutation({
    mutationFn: (suffixes: string[]) => api.setUpnSuffixes(suffixes),
    onSuccess: () => {
      setError(null)
      setDraft(null)
      void queryClient.invalidateQueries({ queryKey: ['upn-management'] })
      // The pickers beside every logon name read the same attribute.
      void queryClient.invalidateQueries({ queryKey: ['upn-suffixes'] })
      onChanged(t('status.saved'))
    },
    onError: setError,
  })

  const add = (event: FormEvent) => {
    event.preventDefault()
    const suffix = entry.trim()
    if (!suffix) return
    const known = [...domains, ...added].some((s) => s.toLowerCase() === suffix.toLowerCase())
    if (!known) setDraft([...added, suffix])
    setEntry('')
  }

  if (listing.isLoading) return <Spinner label={t('status.loading')} />

  return (
    <div className="upn-panel">
      <ErrorMessage error={listing.error} />
      <ErrorMessage error={error} onDismiss={() => setError(null)} />
      <p className="muted">{t('sites.upnIntro')}</p>
      <p className="muted small">
        {t('sites.upnDomains')} <span className="mono">{domains.join(', ')}</span>
      </p>

      <table className="table table--compact">
        <tbody>
          {added.map((suffix) => (
            <tr key={`s-${suffix}`}>
              <td className="mono">{suffix}</td>
              <td />
              <td className="table__actions">
                <button
                  type="button"
                  className="link link--danger"
                  disabled={save.isPending}
                  onClick={() => setDraft(added.filter((s) => s !== suffix))}
                >
                  {t('action.remove')}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <form className="field-inline" onSubmit={add}>
        <input
          type="text"
          value={entry}
          placeholder="corp.example.com"
          autoComplete="off"
          spellCheck={false}
          disabled={save.isPending}
          onChange={(event) => setEntry(event.target.value)}
        />
        <button type="submit" className="button" disabled={!entry.trim() || save.isPending}>
          {t('action.add')}
        </button>
      </form>

      <div className="sheet__actions">
        <span className="muted small">{dirty ? t('detail.unsaved') : t('detail.noChanges')}</span>
        <div className="sheet__buttons">
          <button
            type="button"
            className="button"
            disabled={!dirty || save.isPending}
            onClick={() => {
              setDraft(null)
              setError(null)
            }}
          >
            {t('action.discard')}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate(added)}
          >
            {t('action.save')}
          </button>
        </div>
      </div>
    </div>
  )
}
