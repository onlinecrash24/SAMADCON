/**
 * The advanced audit policy: sixty subcategories in nine categories, from
 * audit.csv — a different file from the rest of this tab, written by its own
 * route and applied by its own client-side extension.
 *
 * Saved per category rather than per row: each save raises the policy
 * version, and a category is the unit an administrator sets together.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../../api/endpoints'
import type { Gpo } from '../../../api/types'
import { ErrorMessage, Spinner } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import type { MessageKey } from '../../../i18n/messages'
import { auditChanges, shownValue } from './auditPolicy'

const VALUES = ['0', '1', '2', '3']

export function AdvancedAudit({
  gpo,
  onChanged,
}: {
  gpo: Gpo
  onChanged: (message: string) => void
}) {
  const { t, language } = useI18n()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [error, setError] = useState<unknown>(null)

  const catalogue = useQuery({ queryKey: ['audit-catalogue'], queryFn: () => api.auditCatalogue() })
  const current = useQuery({ queryKey: ['gpo-audit', gpo.dn], queryFn: () => api.gpoAudit(gpo.dn) })

  const save = useMutation({
    mutationFn: (changes: Record<string, number | null>) =>
      api.setGpoAudit(gpo.dn, { changes, expected_version: current.data?.version_number }),
    onSuccess: (result, changes) => {
      // Both halves of this tab carry the policy version. After either one
      // saves, the other's copy is stale and its next save would be refused
      // as someone else's change.
      void queryClient.invalidateQueries({ queryKey: ['gpo-audit', gpo.dn] })
      void queryClient.invalidateQueries({ queryKey: ['gpo-security', gpo.dn] })
      setDraft((previous) => {
        const next = { ...previous }
        for (const guid of Object.keys(changes)) delete next[guid]
        return next
      })
      setError(null)
      onChanged(result.changed ? t('security.saved') : t('security.unchanged'))
    },
    onError: setError,
  })

  if (catalogue.isLoading || current.isLoading) return <Spinner label={t('status.loading')} />
  if (catalogue.error) return <ErrorMessage error={catalogue.error} />
  if (current.error) return <ErrorMessage error={current.error} />

  const saved = current.data?.settings ?? {}

  return (
    <div className="stack-tight">
      {current.data?.present && !current.data.registered && (
        <div className="alert alert--warning">{t('security.auditNotRegistered')}</div>
      )}
      <ErrorMessage error={error} onDismiss={() => setError(null)} />

      {(catalogue.data?.categories ?? []).map((category) => {
        const guids = category.subcategories.map((sub) => sub.guid)
        const changes = auditChanges(saved, draft, guids)
        return (
          <div key={category.guid} className="card">
            <h4>{language === 'de' ? category.de : category.en}</h4>
            <div className="table-wrap">
              <table className="table table--compact">
                <tbody>
                  {category.subcategories.map((sub) => (
                    <tr key={sub.guid}>
                      <td>{language === 'de' ? sub.de : sub.en}</td>
                      <td className="table__cell--value">
                        <select
                          value={shownValue(saved, draft, sub.guid)}
                          onChange={(event) =>
                            setDraft((previous) => ({ ...previous, [sub.guid]: event.target.value }))
                          }
                        >
                          <option value="">{t('security.notDefined')}</option>
                          {VALUES.map((value) => (
                            <option key={value} value={value}>
                              {t(`security.audit.${value}` as MessageKey)}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pane__actions">
              <button
                type="button"
                className="button"
                disabled={save.isPending || Object.keys(changes).length === 0}
                onClick={() => save.mutate(changes)}
              >
                {t('security.auditSaveCategory')}
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}
