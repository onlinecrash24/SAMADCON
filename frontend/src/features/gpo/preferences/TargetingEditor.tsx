/**
 * The common options and the item-level targeting of one preference item.
 *
 * Laid out as GPMC's "Common" tab and its targeting editor are: four boxes,
 * then a list of conditions read top to bottom, each joined to the one before
 * by AND or OR and each optionally negated ("is not"). Groups, OUs, users and
 * computers are picked from the directory; the server reads name and SID
 * again from the DN, so what is written is the directory's, not the form's.
 *
 * Targeting holding anything else — a collection, an IP range, WMI — is shown
 * as before and left alone: `conditions` is null then, and nothing about it is
 * sent back.
 */

import { useState } from 'react'

import type {
  DirectoryObject,
  ObjectType,
  PreferenceAction,
  PreferenceOptions,
  TargetCondition,
  TargetConditionType,
} from '../../../api/types'
import { useI18n } from '../../../i18n'
import type { MessageKey } from '../../../i18n/messages'
import { useSession } from '../../../state/session'
import { ObjectPicker } from '../../directory/ObjectPicker'
import { conditionFromObject, setOption } from './preferenceOptions'

const PICK_TYPES: Record<TargetConditionType, ObjectType> = {
  group: 'group',
  ou: 'organizational_unit',
  user: 'user',
  computer: 'computer',
}

export function OptionsEditor({
  half,
  options,
  action,
  hasAction,
  targetingEditable,
  onChange,
}: {
  half: string
  options: PreferenceOptions
  action: PreferenceAction | undefined
  hasAction: boolean
  targetingEditable: boolean
  onChange: (options: PreferenceOptions, action: PreferenceAction | undefined) => void
}) {
  const { t } = useI18n()
  const toggle = (name: keyof PreferenceOptions, value: boolean) => {
    const next = setOption(options, hasAction ? action : undefined, name, value)
    onChange(next.options, next.action)
  }
  const box = (name: keyof PreferenceOptions, disabled = false) => (
    <label className="checkbox" key={name}>
      <input
        type="checkbox"
        checked={options[name]}
        disabled={disabled}
        onChange={(event) => toggle(name, event.target.checked)}
      />
      <span>{t(`pref.option.${name}` as MessageKey)}</span>
    </label>
  )

  return (
    <fieldset className="radio-group radio-group--block">
      <legend>{t('pref.options')}</legend>
      {box('stop_on_error')}
      {half === 'User' && box('user_context')}
      {box('remove_policy', options.run_once)}
      {box('run_once', options.remove_policy || !targetingEditable)}
      {options.remove_policy && hasAction && (
        <p className="muted small">{t('pref.option.removeHint')}</p>
      )}
    </fieldset>
  )
}

export function TargetingEditor({
  conditions,
  filterNames,
  onChange,
}: {
  conditions: TargetCondition[] | null
  filterNames: string[]
  onChange: (conditions: TargetCondition[]) => void
}) {
  const { t } = useI18n()
  const { session } = useSession()
  const netbios = session?.domain.netbios_name ?? ''
  const [adding, setAdding] = useState<TargetConditionType | null>(null)
  const [computerName, setComputerName] = useState('')

  if (conditions === null) {
    return (
      <fieldset className="radio-group radio-group--block">
        <legend>{t('pref.targeting')}</legend>
        <div className="alert alert--info">
          {t('pref.filters')}
          <ul className="plain-list">
            {filterNames.map((name) => (
              <li key={name} className="mono small">
                {name}
              </li>
            ))}
          </ul>
        </div>
      </fieldset>
    )
  }

  const edit = (index: number, change: Partial<TargetCondition>) =>
    onChange(conditions.map((entry, at) => (at === index ? { ...entry, ...change } : entry)))

  const add = (condition: TargetCondition) => {
    onChange([...conditions, condition])
    setAdding(null)
    setComputerName('')
  }

  return (
    <fieldset className="radio-group radio-group--block">
      <legend>{t('pref.targeting')}</legend>
      {conditions.length === 0 && <p className="muted small">{t('pref.targeting.none')}</p>}
      {conditions.length > 0 && (
        <div className="table-wrap">
          <table className="table table--compact">
            <tbody>
              {conditions.map((condition, index) => (
                <tr key={`${condition.type}-${condition.name}-${index}`}>
                  <td className="targeting__join">
                    {index === 0 ? null : (
                      <select
                        value={condition.bool}
                        onChange={(event) =>
                          edit(index, { bool: event.target.value as TargetCondition['bool'] })
                        }
                      >
                        <option value="AND">{t('pref.targeting.and')}</option>
                        <option value="OR">{t('pref.targeting.or')}</option>
                      </select>
                    )}
                  </td>
                  <td>
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={condition.not}
                        onChange={(event) => edit(index, { not: event.target.checked })}
                      />
                      <span>{t('pref.targeting.not')}</span>
                    </label>
                  </td>
                  <td>
                    <div className="muted small">
                      {t(`pref.targeting.type.${condition.type}` as MessageKey)}
                    </div>
                    <div className={condition.type === 'ou' ? 'mono small' : undefined}>
                      {condition.name}
                    </div>
                  </td>
                  <td>
                    {(condition.type === 'group' || condition.type === 'ou') && (
                      <select
                        value={condition.user_context === false ? 'computer' : 'user'}
                        onChange={(event) =>
                          edit(index, { user_context: event.target.value === 'user' })
                        }
                      >
                        <option value="user">{t('pref.targeting.forUser')}</option>
                        <option value="computer">{t('pref.targeting.forComputer')}</option>
                      </select>
                    )}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="button button--danger"
                      onClick={() => onChange(conditions.filter((_, at) => at !== index))}
                    >
                      {t('action.remove')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="field-inline">
        {(['group', 'ou', 'user', 'computer'] as TargetConditionType[]).map((type) => (
          <button
            key={type}
            type="button"
            className={adding === type ? 'button button--primary' : 'button'}
            onClick={() => setAdding(adding === type ? null : type)}
          >
            + {t(`pref.targeting.type.${type}` as MessageKey)}
          </button>
        ))}
      </div>

      {adding && (
        <ObjectPicker
          types={[PICK_TYPES[adding]]}
          label={`pref.targeting.type.${adding}` as MessageKey}
          onSelect={(object: DirectoryObject) => add(conditionFromObject(adding, object, netbios))}
        />
      )}
      {adding === 'computer' && (
        <div className="field-inline">
          <input
            value={computerName}
            placeholder={t('pref.targeting.computerName')}
            onChange={(event) => setComputerName(event.target.value)}
          />
          <button
            type="button"
            className="button"
            disabled={!computerName.trim()}
            onClick={() =>
              add({
                type: 'computer',
                bool: 'AND',
                not: false,
                name: computerName.trim(),
                computer_type: 'NETBIOS',
              })
            }
          >
            {t('pref.add')}
          </button>
        </div>
      )}
    </fieldset>
  )
}
