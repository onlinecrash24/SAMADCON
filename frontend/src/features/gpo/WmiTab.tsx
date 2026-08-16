/**
 * The WMI filter a policy uses.
 *
 * Samba does not evaluate these itself — Windows clients do — but a filter
 * assigned to a policy is often the reason it does not apply somewhere, and
 * that is invisible everywhere else.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import type { Gpo } from '../../api/types'
import { Badge, ErrorMessage, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'

export function WmiTab({ gpo, onChanged }: { gpo: Gpo; onChanged: (message: string) => void }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [error, setError] = useState<unknown>(null)

  const assigned = useQuery({
    queryKey: ['gpo-wmi', gpo.dn],
    queryFn: () => api.gpoWmiFilter(gpo.dn),
  })
  const available = useQuery({ queryKey: ['wmi-filters'], queryFn: () => api.wmiFilters() })

  const assign = useMutation({
    mutationFn: (filterDn: string | null) => api.assignWmiFilter(gpo.dn, filterDn),
    onSuccess: () => {
      setError(null)
      void queryClient.invalidateQueries({ queryKey: ['gpo-wmi', gpo.dn] })
      onChanged(t('gpo.saved'))
    },
    onError: setError,
  })

  if (assigned.isLoading || available.isLoading) return <Spinner label={t('status.loading')} />
  if (assigned.error) return <ErrorMessage error={assigned.error} />

  const current = assigned.data?.filter ?? null
  const filters = available.data?.filters ?? []

  return (
    <div className="stack-tight">
      <ErrorMessage error={error} onDismiss={() => setError(null)} />
      <p className="muted small">{t('gpo.wmiHint')}</p>

      {filters.length === 0 && !current ? (
        <p className="muted">{t('gpo.noWmiFilters')}</p>
      ) : (
        <label className="field">
          <span className="field__label">{t('gpo.wmiFilter')}</span>
          <select
            value={current?.dn ?? ''}
            disabled={assign.isPending}
            onChange={(event) => assign.mutate(event.target.value || null)}
          >
            <option value="">{t('gpo.noWmiFilter')}</option>
            {filters.map((filter) => (
              <option key={filter.dn ?? filter.id} value={filter.dn ?? ''}>
                {filter.name ?? filter.id}
              </option>
            ))}
          </select>
        </label>
      )}

      {current?.missing && (
        // A policy pointing at a filter that is gone applies nowhere, which is
        // the opposite of having no filter at all.
        <div className="alert alert--warning">
          {t('gpo.wmiMissing', { id: current.id })}
        </div>
      )}

      {current && !current.missing && (
        <section className="card">
          <h4>
            {current.name} {current.description && <Badge tone="muted">{current.description}</Badge>}
          </h4>
          {current.queries.map((query, index) => (
            <div key={index} className="stack-tight">
              <span className="muted small">{query.namespace}</span>
              <code className="mono small">{query.query}</code>
            </div>
          ))}
        </section>
      )}
    </div>
  )
}
