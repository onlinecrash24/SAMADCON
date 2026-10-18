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
 *
 * An edit goes into the property sheet's draft and is written with OK or
 * Apply, as every other tab's is and as ADUC's attribute editor does. It
 * used to write when its own small dialog was confirmed.
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { api } from '../../api/endpoints'
import type { AttributeEntry } from '../../api/types'
import { Badge, ErrorMessage, Modal, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n/messages'
import { readShowEmptyAttributes, writeShowEmptyAttributes } from '../../state/showEmptyAttributes'
import { attributeRows, cannotSave, valuesFromText } from './attributeRows'
import { withRawAttribute } from './sheet/draft'
import { useSheet } from './sheet/SheetContext'

interface AttributeEditorProps {
  dn: string
}

/** The text values the editor shows for an entry, as the draft compares them. */
function textValues(entry: AttributeEntry): string[] {
  return entry.values.map((value) => value.text ?? '')
}

export function AttributeEditor({ dn }: AttributeEditorProps) {
  const { t } = useI18n()
  const sheet = useSheet()

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
              <td className="attrs__name mono">
                {name}
                {sheet.draft.raw[name] && (
                  <div>
                    <Badge tone="warn">{t('sheet.queued')}</Badge>
                  </div>
                )}
              </td>
              <td className="attrs__value">
                {sheet.draft.raw[name] &&
                  (sheet.draft.raw[name].after.length === 0 ? (
                    <span className="muted">{t('attributes.notSet')}</span>
                  ) : (
                    sheet.draft.raw[name].after.map((value, index) => (
                      <div key={index} className="attrs__item">
                        <span className="mono">{value}</span>
                      </div>
                    ))
                  ))}
                {!sheet.draft.raw[name] && entry.values.length === 0 && (
                  <span className="muted">{t('attributes.notSet')}</span>
                )}
                {!sheet.draft.raw[name] && entry.values.map((value, index) => (
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
                    disabled={sheet.busy}
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
          current={sheet.draft.raw[editing.name]?.after ?? textValues(editing.entry)}
          onClose={() => setEditing(null)}
          onSave={(values) => {
            const { name, entry } = editing
            sheet.setDraft((draft) => withRawAttribute(draft, name, textValues(entry), values))
            setEditing(null)
          }}
        />
      )}
    </section>
  )
}

function AttributeDialog({
  name,
  entry,
  current,
  onClose,
  onSave,
}: {
  name: string
  entry: AttributeEntry
  /** What the draft holds for it, or the directory's values when untouched. */
  current: string[]
  onClose: () => void
  onSave: (values: string[]) => void
}) {
  const { t } = useI18n()
  const [text, setText] = useState(() => current.join('\n'))

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
            disabled={blocked !== null}
            onClick={() => onSave(values)}
          >
            {t('action.ok')}
          </button>
        </>
      }
    >
      <div className="form">
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
