import { useState } from 'react'

import { Modal } from '../../../components/primitives'
import { useI18n } from '../../../i18n'

/**
 * ADUC's "(Other)" dialog: a new value and Add, the current values, Edit and
 * Remove, OK and Cancel.
 *
 * It edits a copy and hands the list back on OK; Cancel throws the copy
 * away. The list then sits in the sheet's draft like any other field and
 * reaches the directory with the sheet's OK — a second level of "not yet",
 * which is exactly how the original nests it.
 *
 * Edit takes the value back into the input and out of the list, so editing
 * is typing it again and pressing Add. That is what ADUC does, and it means
 * there is one input and one rule for what goes into the list.
 */
export function OtherValuesDialog({
  title,
  values,
  onClose,
  onSave,
}: {
  title: string
  values: string[]
  onClose: () => void
  onSave: (values: string[]) => void
}) {
  const { t } = useI18n()
  const [list, setList] = useState<string[]>(values)
  const [entry, setEntry] = useState('')

  const add = () => {
    const value = entry.trim()
    if (!value) return
    if (!list.some((v) => v.toLowerCase() === value.toLowerCase())) setList([...list, value])
    setEntry('')
  }

  return (
    <Modal
      title={title}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button button--primary" onClick={() => onSave(list)}>
            {t('action.ok')}
          </button>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
        </>
      }
    >
      <div className="form">
        <label className="field">
          <span className="field__label">{t('others.newValue')}</span>
          <div className="field-inline">
            <input
              type="text"
              value={entry}
              autoComplete="off"
              onChange={(event) => setEntry(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  add()
                }
              }}
            />
            <button type="button" className="button" disabled={!entry.trim()} onClick={add}>
              {t('action.add')}
            </button>
          </div>
        </label>

        <div className="field">
          <span className="field__label">{t('others.currentValues')}</span>
          {list.length === 0 ? (
            <p className="muted small">{t('others.none')}</p>
          ) : (
            <ul className="plain-list boxed-list">
              {list.map((value) => (
                <li key={value} className="others__row">
                  <span className="others__value">{value}</span>
                  <span className="others__actions">
                    <button
                      type="button"
                      className="link"
                      onClick={() => {
                        setEntry(value)
                        setList(list.filter((v) => v !== value))
                      }}
                    >
                      {t('action.edit')}
                    </button>
                    <button
                      type="button"
                      className="link link--danger"
                      onClick={() => setList(list.filter((v) => v !== value))}
                    >
                      {t('action.remove')}
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Modal>
  )
}
