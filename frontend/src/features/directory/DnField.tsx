import { useState } from 'react'

import type { ObjectType } from '../../api/types'
import { Modal } from '../../components/primitives'
import { nameFromDn } from '../../dn'
import { useI18n } from '../../i18n'
import { ObjectPicker } from './ObjectPicker'

/**
 * A field whose value is another object — the manager, the group's owner.
 *
 * ADUC draws these as a name with "Change…" and "Clear" beside it, and it is
 * right to: the value is a distinguished name, and a distinguished name is
 * something one picks, not something one types. The field used to be a text
 * box with a hint saying "the object's distinguished name", which is a way of
 * asking an administrator to get a 60-character string exactly right.
 *
 * The name shown is the leading component of the DN. The full DN is on the
 * title, for whoever needs to tell two objects of one name apart.
 */
export function DnField({
  value,
  onChange,
  types,
  disabled,
}: {
  value: string
  onChange: (next: string) => void
  /** What may be chosen — a manager is a person, a group's owner may be a group. */
  types: ObjectType[]
  disabled?: boolean
}) {
  const { t } = useI18n()
  const [picking, setPicking] = useState(false)

  return (
    <div className="dn-field">
      <span className="dn-field__name" title={value || undefined}>
        {value ? nameFromDn(value) : <span className="muted">{t('dnField.none')}</span>}
      </span>
      <button type="button" className="button" disabled={disabled} onClick={() => setPicking(true)}>
        {t('dnField.change')}
      </button>
      <button
        type="button"
        className="button"
        disabled={disabled || !value}
        onClick={() => onChange('')}
      >
        {t('dnField.clear')}
      </button>

      {picking && (
        <Modal
          title={t('dnField.pick')}
          onClose={() => setPicking(false)}
          footer={
            <button type="button" className="button" onClick={() => setPicking(false)}>
              {t('action.cancel')}
            </button>
          }
        >
          <div className="form">
            <ObjectPicker
              types={types}
              onSelect={(chosen) => {
                onChange(chosen.dn)
                setPicking(false)
              }}
            />
          </div>
        </Modal>
      )}
    </div>
  )
}
