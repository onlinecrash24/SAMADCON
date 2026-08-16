/**
 * Raw attribute editor — the escape hatch for everything the typed property
 * sheets do not cover.
 *
 * Multi-valued attributes are edited one value per line, which is how the
 * directory thinks about them and avoids inventing a separator that could
 * appear inside a value. Whether an attribute may be written at all is decided
 * by the server and reported per attribute; this component only renders that
 * decision.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { api } from '../../api/endpoints'
import type { AttributeEntry } from '../../api/types'
import { Badge, ErrorMessage, Modal, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'

interface AttributeEditorProps {
  dn: string
  onChanged: (message: string) => void
}

export function AttributeEditor({ dn, onChanged }: AttributeEditorProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const [filter, setFilter] = useState('')
  const [editing, setEditing] = useState<{ name: string; entry: AttributeEntry } | null>(null)

  const listing = useQuery({
    queryKey: ['attributes', dn],
    queryFn: () => api.attributes(dn),
  })

  const rows = useMemo(() => {
    const entries = Object.entries(listing.data?.attributes ?? {})
    const needle = filter.trim().toLowerCase()
    const matching = needle
      ? entries.filter(([name]) => name.toLowerCase().includes(needle))
      : entries
    return matching.sort(([a], [b]) => a.localeCompare(b))
  }, [listing.data, filter])

  const save = useMutation({
    mutationFn: ({ name, values }: { name: string; values: string[] }) =>
      api.updateAttributes(dn, {
        // An empty list means "remove the attribute"; the API spells that null.
        [name]: values.length === 0 ? null : values.length === 1 ? values[0]! : values,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['attributes', dn] })
      void queryClient.invalidateQueries({ queryKey: ['object-detail'] })
      setEditing(null)
      onChanged(t('status.saved'))
    },
  })

  return (
    <section className="detail__section">
      <input
        type="search"
        className="list__filter"
        placeholder={t('attributes.filter')}
        value={filter}
        onChange={(event) => setFilter(event.target.value)}
      />

      {listing.isLoading && <Spinner label={t('status.loading')} />}
      <ErrorMessage error={listing.error} />

      <table className="attrs">
        <tbody>
          {rows.map(([name, entry]) => (
            <tr key={name}>
              <td className="attrs__name mono">{name}</td>
              <td className="attrs__value">
                {entry.values.map((value, index) => (
                  <div key={index} className="attrs__item">
                    {value.text !== undefined ? (
                      <span className="mono">{value.text}</span>
                    ) : (
                      <span className="muted mono">
                        {t('attributes.binary', { size: value.size ?? 0 })}
                      </span>
                    )}
                  </div>
                ))}
              </td>
              <td className="attrs__action">
                {entry.editable ? (
                  <button
                    type="button"
                    className="link"
                    onClick={() => setEditing({ name, entry })}
                  >
                    {t('action.edit')}
                  </button>
                ) : (
                  <Badge tone="muted">{t('attributes.readonly')}</Badge>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {editing && (
        <AttributeDialog
          name={editing.name}
          entry={editing.entry}
          saving={save.isPending}
          error={save.error}
          onClose={() => {
            save.reset()
            setEditing(null)
          }}
          onSave={(values) => save.mutate({ name: editing.name, values })}
        />
      )}
    </section>
  )
}

function AttributeDialog({
  name,
  entry,
  saving,
  error,
  onClose,
  onSave,
}: {
  name: string
  entry: AttributeEntry
  saving: boolean
  error: unknown
  onClose: () => void
  onSave: (values: string[]) => void
}) {
  const { t } = useI18n()
  const [text, setText] = useState(() =>
    entry.values.map((value) => value.text ?? '').join('\n'),
  )

  const values = text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)

  return (
    <Modal
      title={name}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={saving}
            onClick={() => onSave(values)}
          >
            {t('action.save')}
          </button>
        </>
      }
    >
      <div className="form">
        <ErrorMessage error={error} />
        <p className="muted small">{t('attributes.multivalueHint')}</p>
        <textarea
          rows={Math.min(Math.max(entry.values.length, 2), 12)}
          className="mono"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        {values.length === 0 && <p className="login__insecure">{t('attributes.willDelete')}</p>}
      </div>
    </Modal>
  )
}
