/**
 * The DNS console: zones on the left, the records of the selected zone here.
 *
 * Records are listed one per row rather than grouped by name, which is how a
 * zone file reads and how people look for them. Read-only types (SOA) are
 * shown but not offered for editing.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { api } from '../../api/endpoints'
import type { DnsRecord, DnsZone } from '../../api/types'
import { Badge, ErrorMessage, Modal, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'
import { RecordDialog } from './RecordDialog'

interface DnsViewProps {
  zone: DnsZone | null
  onChanged: (message: string) => void
}

export function DnsView({ zone, onChanged }: DnsViewProps) {
  const { t, tn } = useI18n()
  const queryClient = useQueryClient()

  const [filter, setFilter] = useState('')
  const [editing, setEditing] = useState<DnsRecord | null>(null)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<DnsRecord | null>(null)
  const [error, setError] = useState<unknown>(null)

  const types = useQuery({
    queryKey: ['dns-record-types'],
    queryFn: () => api.dnsRecordTypes(),
    staleTime: Infinity,
  })

  const listing = useQuery({
    queryKey: ['dns-records', zone?.dn],
    queryFn: () => api.dnsRecords(zone!.dn, zone!.name),
    enabled: Boolean(zone),
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['dns-records', zone?.dn] })
  }

  const remove = useMutation({
    mutationFn: (record: DnsRecord) =>
      api.deleteDnsRecord(zone!.dn, {
        zone: zone!.name,
        name: record.node,
        type: record.type,
        data: record.data,
      }),
    onSuccess: () => {
      setError(null)
      setDeleting(null)
      refresh()
      onChanged(t('dns.recordDeleted'))
    },
    onError: setError,
  })

  const records = useMemo(() => {
    const all = listing.data?.records ?? []
    const needle = filter.trim().toLowerCase()
    if (!needle) return all
    return all.filter((record) =>
      [record.name, record.type, record.display].some((value) =>
        value.toLowerCase().includes(needle),
      ),
    )
  }, [listing.data, filter])

  if (!zone) {
    return (
      <div className="placeholder">
        <h2>{t('snapin.dns')}</h2>
        <p className="muted">{t('dns.pickZone')}</p>
      </div>
    )
  }

  return (
    <>
      <div className="pane__header">
        <span className="mono muted small">
          {zone.name}
          {zone.reverse && <> · {t('dns.reverseZone')}</>}
        </span>
        <div className="pane__actions">
          <button type="button" className="button" onClick={() => setCreating(true)}>
            + {t('dns.newRecord')}
          </button>
        </div>
      </div>

      <div className="list">
        <div className="list__toolbar">
          <input
            type="search"
            className="list__filter"
            placeholder={t('list.filter')}
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
          <span className="list__count">{tn('dns.recordCount', records.length)}</span>
        </div>

        <ErrorMessage error={error} onDismiss={() => setError(null)} />
        <ErrorMessage error={listing.error} />
        {listing.isLoading && <Spinner label={t('status.loading')} />}

        {records.length === 0 && !listing.isLoading ? (
          <p className="list__empty">{t('dns.noRecords')}</p>
        ) : (
          <table className="list__table">
            <thead>
              <tr>
                <th>{t('list.name')}</th>
                <th>{t('dns.recordType')}</th>
                <th>{t('dns.value')}</th>
                <th>{t('dns.ttl')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {records.map((record) => (
                <tr key={`${record.dn}-${record.index}`} className="list__row">
                  <td>
                    {record.node === '@' ? (
                      <span className="muted">{t('dns.zoneItself')}</span>
                    ) : (
                      record.node
                    )}
                  </td>
                  <td>
                    {record.type}
                    {record.timestamp > 0 && <Badge tone="muted">{t('dns.aging')}</Badge>}
                  </td>
                  <td className="mono">{record.display}</td>
                  <td className="muted">{record.ttl}</td>
                  <td className="attrs__action">
                    {record.editable && (
                      <>
                        <button type="button" className="link" onClick={() => setEditing(record)}>
                          {t('action.edit')}
                        </button>{' '}
                        <button type="button" className="link" onClick={() => setDeleting(record)}>
                          {t('action.delete')}
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {(creating || editing) && (
        <RecordDialog
          zone={zone.name}
          zoneDn={zone.dn}
          defaultTtl={types.data?.default_ttl ?? 900}
          existing={editing ?? undefined}
          onClose={() => {
            setCreating(false)
            setEditing(null)
          }}
          onDone={(message) => {
            setCreating(false)
            setEditing(null)
            refresh()
            onChanged(message)
          }}
        />
      )}

      {deleting && (
        <Modal
          title={t('dialog.deleteTitle', { name: deleting.name })}
          onClose={() => setDeleting(null)}
          footer={
            <>
              <button type="button" className="button" onClick={() => setDeleting(null)}>
                {t('action.cancel')}
              </button>
              <button
                type="button"
                className="button button--danger"
                disabled={remove.isPending}
                onClick={() => remove.mutate(deleting)}
              >
                {t('action.delete')}
              </button>
            </>
          }
        >
          <div className="form">
            <ErrorMessage error={remove.error} />
            <p>{t('dialog.deleteBody')}</p>
            <p className="mono">
              {deleting.name} {deleting.type} {deleting.display}
            </p>
          </div>
        </Modal>
      )}
    </>
  )
}
