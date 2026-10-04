/**
 * Raw attribute editor — the escape hatch for everything the typed property
 * sheets do not cover.
 *
 * Multi-valued attributes are edited one value per line, which is how the
 * directory thinks about them and avoids inventing a separator that could
 * appear inside a value. Whether an attribute may be written at all is decided
 * by the server and reported per attribute; this component only renders that
 * decision.
 *
 * Attributes without a value are listed on request, as RSAT lists them: the
 * server asks the directory which ones the object may have and which of those
 * the signed-in account may write.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { api } from '../../api/endpoints'
import type { AttributeEntry } from '../../api/types'
import { Badge, ErrorMessage, Modal, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n/messages'
import { readShowEmptyAttributes, writeShowEmptyAttributes } from '../../state/showEmptyAttributes'
import { attributeRows, cannotSave, valuesFromText } from './attributeRows'

interface AttributeEditorProps {
  dn: string
  onChanged: (message: string) => void
}

export function AttributeEditor({ dn, onChanged }: AttributeEditorProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const [filter, setFilter] = useState('')
  const [showEmpty, setShowEmpty] = useState(readShowEmptyAttributes)
  const [editing, setEditing] = useState<{ name: string; entry: AttributeEntry } | null>(null)

  const listing = useQuery({
    queryKey: ['attributes', dn, showEmpty],
    queryFn: () => api.attributes(dn, showEmpty),
  })

  const rows = useMemo(
    () => attributeRows(listing.data?.attributes ?? {}, filter),
    [listing.data, filter],
  )

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
      <label className="checkbox">
        <input
          type="checkbox"
          checked={showEmpty}
          onChange={(event) => {
            setShowEmpty(event.target.checked)
            writeShowEmptyAttributes(event.target.checked)
          }}
        />
        {t('attributes.showEmpty')}
      </label>

      {listing.isLoading && <Spinner label={t('status.loading')} />}
      <ErrorMessage error={listing.error} />

      <table className="attrs">
        <tbody>
          {rows.map(([name, entry]) => (
            <tr key={name}>
              <td className="attrs__name mono">{name}</td>
              <td className="attrs__value">
                {entry.values.length === 0 && (
                  <span className="muted">{t('attributes.notSet')}</span>
                )}
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
                  <span
                    title={
                      entry.note ? t(`attributes.note.${entry.note}` as MessageKey) : undefined
                    }
                  >
                    <Badge tone="muted">{t('attributes.readonly')}</Badge>
                  </span>
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

  const values = valuesFromText(text)
  const blocked = cannotSave(entry, values)

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
            disabled={saving || blocked !== null}
            onClick={() => onSave(values)}
          >
            {t('action.save')}
          </button>
        </>
      }
    >
      <div className="form">
        <ErrorMessage error={error} />
        <p className="muted small">
          {entry.single_valued === true
            ? t('attributes.singleValueHint')
            : t('attributes.multivalueHint')}
        </p>
        <textarea
          rows={Math.min(Math.max(entry.values.length, 2), 12)}
          className="mono"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        {blocked === 'single_valued' && (
          <p className="login__insecure">{t('attributes.tooManyValues')}</p>
        )}
        {values.length === 0 && entry.values.length > 0 && (
          <p className="login__insecure">{t('attributes.willDelete')}</p>
        )}
      </div>
    </Modal>
  )
}
