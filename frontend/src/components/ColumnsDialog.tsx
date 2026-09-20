import { useState } from 'react'

import { useI18n } from '../i18n'
import { COLUMN_CATALOGUE, DEFAULT_COLUMNS, columnDef, normaliseColumns } from '../state/listColumns'
import { Modal } from './primitives'

/**
 * ADUC's Add/Remove Columns: available on the left, displayed on the right,
 * Add and Remove between them, Move Up and Move Down beside the right-hand
 * list, Restore Defaults, OK and Cancel.
 *
 * Edits a copy; OK hands it back. Name cannot be removed or moved off the
 * top — it is what a row is — so it is drawn in the list but greyed, the way
 * the original greys it.
 */
export function ColumnsDialog({
  columns,
  onClose,
  onSave,
}: {
  columns: readonly string[]
  onClose: () => void
  onSave: (columns: string[]) => void
}) {
  const { t } = useI18n()
  const [shown, setShown] = useState<string[]>(normaliseColumns(columns))
  const [pickAvailable, setPickAvailable] = useState<string | null>(null)
  const [pickShown, setPickShown] = useState<string | null>(null)

  const available = COLUMN_CATALOGUE.map((c) => c.id).filter((id) => !shown.includes(id))
  const shownIndex = pickShown ? shown.indexOf(pickShown) : -1
  const canRemove = shownIndex > 0
  const canUp = shownIndex > 1
  const canDown = shownIndex > 0 && shownIndex < shown.length - 1

  const label = (id: string) => t(columnDef(id)?.label ?? 'list.name')

  const add = () => {
    if (!pickAvailable) return
    setShown([...shown, pickAvailable])
    setPickShown(pickAvailable)
    setPickAvailable(null)
  }
  const remove = () => {
    if (!canRemove) return
    setShown(shown.filter((id) => id !== pickShown))
    setPickAvailable(pickShown)
    setPickShown(null)
  }
  const move = (delta: number) => {
    const next = [...shown]
    const at = shownIndex
    const to = at + delta
    if (at <= 0 || to <= 0 || to >= next.length) return
    ;[next[at], next[to]] = [next[to]!, next[at]!]
    setShown(next)
  }

  return (
    <Modal
      wide
      title={t('columns.title')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button button--primary" onClick={() => onSave(shown)}>
            {t('action.ok')}
          </button>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
        </>
      }
    >
      <div className="columns">
        <div className="columns__list">
          <span className="field__label">{t('columns.available')}</span>
          <select
            size={12}
            value={pickAvailable ?? ''}
            onChange={(event) => setPickAvailable(event.target.value)}
            onDoubleClick={add}
          >
            {available.map((id) => (
              <option key={id} value={id}>
                {label(id)}
              </option>
            ))}
          </select>
        </div>

        <div className="columns__between">
          <button type="button" className="button" disabled={!pickAvailable} onClick={add}>
            {t('columns.add')}
          </button>
          <button type="button" className="button" disabled={!canRemove} onClick={remove}>
            {t('columns.remove')}
          </button>
        </div>

        <div className="columns__list">
          <span className="field__label">{t('columns.shown')}</span>
          <select
            size={12}
            value={pickShown ?? ''}
            onChange={(event) => setPickShown(event.target.value)}
            onDoubleClick={remove}
          >
            {shown.map((id) => (
              <option key={id} value={id} disabled={id === 'name'}>
                {label(id)}
              </option>
            ))}
          </select>
        </div>

        <div className="columns__side">
          <button type="button" className="button" disabled={!canUp} onClick={() => move(-1)}>
            {t('columns.up')}
          </button>
          <button type="button" className="button" disabled={!canDown} onClick={() => move(1)}>
            {t('columns.down')}
          </button>
          <button
            type="button"
            className="button"
            onClick={() => {
              setShown(DEFAULT_COLUMNS)
              setPickShown(null)
              setPickAvailable(null)
            }}
          >
            {t('columns.restore')}
          </button>
        </div>
      </div>
    </Modal>
  )
}
