/**
 * Group policy preferences — the editor's "Einstellungen" branch.
 *
 * Laid out as items rather than as a table: a drive map carries eight fields
 * and a shortcut twelve, and a row wide enough for all of them is a row nobody
 * can read. Each item is a small form, which is also closer to what the
 * console shows.
 *
 * The form comes from the server's catalogue rather than from here, down to
 * which fields exist and which values a choice offers. Adding a preference
 * type is then a change in one Python file — this tab needs a label and
 * nothing else.
 *
 * Two things the editor deliberately shows but does not touch:
 *
 * * **Item-level targeting.** It is displayed and left alone. Sending it back
 *   with every save would mean a rename could drop the filter that decides
 *   who a drive is mapped for — silently, and in the permissive direction.
 * * **A stored password.** The key for `cpassword` has been public since 2014.
 *   An item that has one keeps it; nothing here can add one.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { api } from '../../../api/endpoints'
import type {
  DirectoryObject,
  Gpo,
  PreferenceAction,
  PreferenceField,
  PreferenceItem,
  PreferenceKind,
  PreferenceMember,
  PreferenceTypeId,
} from '../../../api/types'
import { ErrorMessage, Spinner } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import { useSession } from '../../../state/session'
import { ObjectPicker } from '../../directory/ObjectPicker'
import type { MessageKey } from '../../../i18n/messages'

const HALVES = ['Machine', 'User'] as const
const MULTI_SZ = 'REG_MULTI_SZ'

/** What the browser sends back: never the filters, never the unknown parts. */
interface Draft {
  kind: string
  uid?: string
  /** Absent for a service, which has no Create/Replace/Update/Delete. */
  action?: PreferenceAction
  properties: Record<string, string>
  values?: string[]
  members?: PreferenceMember[]
  /** Read only, for the item's own heading. */
  name: string
  filter_names: string[]
  has_password: boolean
}

export function PreferencesTab({
  gpo,
  onChanged,
}: {
  gpo: Gpo
  onChanged: (message: string) => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const [selected, setSelected] = useState<{ type: PreferenceTypeId; half: string }>({
    type: 'registry',
    half: 'Machine',
  })
  const [draft, setDraft] = useState<Draft[]>([])
  const [error, setError] = useState<unknown>(null)

  const catalogue = useQuery({
    queryKey: ['preference-types'],
    queryFn: () => api.preferenceTypes(),
  })
  const current = useQuery({
    queryKey: ['gpo-preferences', gpo.dn],
    queryFn: () => api.gpoPreferences(gpo.dn),
  })

  const items = current.data?.types?.[selected.type]?.halves?.[selected.half]?.items

  useEffect(() => {
    setDraft((items ?? []).map(toDraft))
  }, [items])

  const save = useMutation({
    mutationFn: () =>
      api.setGpoPreferences(gpo.dn, {
        type: selected.type,
        half: selected.half,
        items: draft.map(({ kind, uid, action, properties, values, members }) => ({
          kind,
          uid,
          action,
          properties,
          values,
          members,
        })),
        expected_version: current.data?.version_number,
      }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['gpo-preferences', gpo.dn] })
      onChanged(result.changed ? t('pref.saved') : t('pref.unchanged'))
    },
    onError: setError,
  })

  if (catalogue.isLoading || current.isLoading) return <Spinner label={t('status.loading')} />
  if (catalogue.error) return <ErrorMessage error={catalogue.error} />
  if (current.error) return <ErrorMessage error={current.error} />

  const types = catalogue.data?.types ?? []
  const actions = catalogue.data?.actions ?? []
  const type = types.find((item) => item.id === selected.type)
  // Printers are the only type where this is more than one; the "+ Eintrag"
  // row then offers a button per kind instead of a single one.
  const kinds = (type?.kinds ?? []).filter((kind) => kind.halves.includes(selected.half))

  const edit = (index: number, change: Partial<Draft>) =>
    setDraft(draft.map((item, at) => (at === index ? { ...item, ...change } : item)))

  return (
    <div className="gpedit">
      <div className="gpedit__panes">
        <nav className="gpedit__tree" aria-label={t('gpo.tab.preferences')}>
          {HALVES.map((half) => (
            <div key={half}>
              <div className="cats__group">
                {t(half === 'Machine' ? 'pref.machine' : 'pref.user')}
              </div>
              <ul className="cats">
                {types
                  .filter((item) => item.halves.includes(half))
                  .map((item) => (
                    <li key={`${half}-${item.id}`}>
                      <button
                        type="button"
                        className={
                          selected.type === item.id && selected.half === half
                            ? 'cats__node cats__node--active'
                            : 'cats__node'
                        }
                        onClick={() => setSelected({ type: item.id, half })}
                      >
                        <span className="cats__name">
                          {t(`pref.type.${item.id}` as MessageKey)}
                        </span>
                        <Count
                          count={
                            current.data?.types?.[item.id]?.halves?.[half]?.items?.length ?? 0
                          }
                        />
                      </button>
                    </li>
                  ))}
              </ul>
            </div>
          ))}
        </nav>

        <section className="gpedit__list">
          <ErrorMessage error={error} onDismiss={() => setError(null)} />

          <p className="muted small">{t(`pref.hint.${selected.type}` as MessageKey)}</p>

          {draft.length === 0 && <p className="muted">{t('pref.none')}</p>}

          {draft.map((item, index) => {
            const kind = kinds.find((entry) => entry.id === item.kind) ?? kinds[0]
            if (!kind) return null
            return (
              <ItemForm
                key={item.uid ?? `new-${index}`}
                type={selected.type}
                kind={kind}
                showKind={kinds.length > 1}
                actions={actions}
                item={item}
                onChange={(change) => edit(index, change)}
                onRemove={() => setDraft(draft.filter((_, at) => at !== index))}
              />
            )
          })}

          <div className="pane__actions">
            {kinds
              .filter((kind) => kind.creatable)
              .map((kind) => (
              <button
                key={kind.id}
                type="button"
                className="button"
                onClick={() => setDraft([...draft, blank(kind)])}
              >
                + {kinds.length > 1 ? t(`pref.kind.${kind.id}` as MessageKey) : t('pref.add')}
              </button>
              ))}
            <button
              type="button"
              className="button button--primary"
              disabled={save.isPending}
              onClick={() => save.mutate()}
            >
              {t('action.save')}
            </button>
          </div>
        </section>
      </div>
    </div>
  )
}

function Count({ count }: { count: number }) {
  if (!count) return null
  return <span className="muted small">{count}</span>
}

function toDraft(item: PreferenceItem): Draft {
  return {
    kind: item.kind,
    uid: item.uid,
    action: item.action ? (item.action as PreferenceAction) : undefined,
    properties: { ...item.properties },
    values: item.values,
    members: item.members,
    name: item.name,
    filter_names: item.filter_names,
    has_password: item.has_password,
  }
}

function blank(kind: PreferenceKind): Draft {
  const properties: Record<string, string> = {}
  for (const field of kind.fields) properties[field.name] = field.default
  return {
    kind: kind.id,
    action: kind.has_action ? 'C' : undefined,
    properties,
    values: [],
    members: [],
    name: '',
    filter_names: [],
    has_password: false,
  }
}

function ItemForm({
  type,
  kind,
  showKind,
  actions,
  item,
  onChange,
  onRemove,
}: {
  type: PreferenceTypeId
  kind: PreferenceKind
  showKind: boolean
  actions: PreferenceAction[]
  item: Draft
  onChange: (change: Partial<Draft>) => void
  onRemove: () => void
}) {
  const { t } = useI18n()
  const setProperty = (name: string, value: string) =>
    onChange({ properties: { ...item.properties, [name]: value } })

  // The lines of a REG_MULTI_SZ live in their own block, not in the value
  // attribute, so the value box turns into a text area for that one type.
  const multiLine = type === 'registry' && item.properties.type === MULTI_SZ

  return (
    <div className="card stack-tight">
      <div className="field-inline">
        <strong>{item.name || t('pref.newItem')}</strong>
        {showKind && (
          <span className="badge">{t(`pref.kind.${kind.id}` as MessageKey)}</span>
        )}
        {kind.has_action && (
          <select
            value={item.action ?? 'C'}
            onChange={(event) => onChange({ action: event.target.value as PreferenceAction })}
          >
            {actions.map((action) => (
              <option key={action} value={action}>
                {t(`pref.action.${action}` as MessageKey)}
              </option>
            ))}
          </select>
        )}
        <button type="button" className="button button--danger" onClick={onRemove}>
          {t('action.remove')}
        </button>
      </div>

      {item.has_password && <div className="alert alert--warning">{t('pref.password')}</div>}
      {!kind.creatable && <div className="alert alert--info">{t('pref.notCreatable')}</div>}
      {item.filter_names.length > 0 && (
        <div className="alert alert--info">
          {t('pref.filters')}
          <ul className="plain-list">
            {item.filter_names.map((name) => (
              <li key={name} className="mono small">
                {name}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="field-row">
        {kind.fields.map((field) =>
          multiLine && field.name === 'value' ? (
            <label className="field" key={field.name}>
              <span className="field__label">{t('pref.field.value' as MessageKey)}</span>
              <textarea
                rows={4}
                placeholder={t('pref.multiline')}
                value={(item.values ?? []).join('\n')}
                onChange={(event) =>
                  onChange({ values: event.target.value.split('\n').filter(Boolean) })
                }
              />
            </label>
          ) : (
            <FieldInput
              key={field.name}
              kindId={kind.id}
              field={field}
              value={item.properties[field.name] ?? field.default}
              onChange={(value) => setProperty(field.name, value)}
            />
          ),
        )}
      </div>

      {kind.id === 'group' && (
        <Members
          members={item.members ?? []}
          onChange={(members) => onChange({ members })}
        />
      )}
    </div>
  )
}

/**
 * The members of a local group.
 *
 * The name is picked rather than typed. GPMC writes both a qualified name and
 * a SID for every member, and a hand-typed name gives neither reliably: a
 * typo produces an entry that applies to nobody and reports no error. The
 * picker is the same one the ACL editor uses, so a group found there is found
 * here.
 *
 * Each member carries a direction of its own — ADD and REMOVE sit in the same
 * list, and the server refuses one without it. A default either way would be a
 * wrong answer, and one of them grants access.
 */
function Members({
  members,
  onChange,
}: {
  members: PreferenceMember[]
  onChange: (members: PreferenceMember[]) => void
}) {
  const { t } = useI18n()
  const { session } = useSession()
  const domain = session?.domain.netbios_name ?? ''

  const edit = (index: number, change: Partial<PreferenceMember>) =>
    onChange(members.map((entry, at) => (at === index ? { ...entry, ...change } : entry)))

  const add = (object: DirectoryObject) => {
    const account = object.sam_account_name ?? object.name
    // DOMAIN\account, which is the form GPMC writes into `name`.
    const name = domain ? `${domain}\\${account}` : account
    if (members.some((member) => member.name === name)) return
    onChange([...members, { name, action: 'ADD', sid: object.sid }])
  }

  return (
    <div className="stack-tight">
      <span className="field__label">{t('pref.members')}</span>

      {members.length > 0 && (
        <div className="table-wrap">
          <table className="table table--compact">
            <thead>
              <tr>
                <th>{t('pref.member.name')}</th>
                <th className="table__cell--action">{t('pref.action')}</th>
                <th className="table__cell--narrow" />
              </tr>
            </thead>
            <tbody>
              {members.map((member, index) => (
                <tr key={member.name || index}>
                  <td>
                    <div>{member.name}</div>
                    {member.sid && <div className="muted small mono">{member.sid}</div>}
                  </td>
                  <td className="table__cell--action">
                    <select
                      value={member.action}
                      onChange={(event) =>
                        edit(index, { action: event.target.value as PreferenceMember['action'] })
                      }
                    >
                      <option value="ADD">{t('pref.member.add')}</option>
                      <option value="REMOVE">{t('pref.member.remove')}</option>
                    </select>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="button button--danger"
                      onClick={() => onChange(members.filter((_, at) => at !== index))}
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

      <ObjectPicker types={['user', 'group', 'computer']} label="pref.members" onSelect={add} />
    </div>
  )
}

function FieldInput({
  kindId,
  field,
  value,
  onChange,
}: {
  kindId: string
  field: PreferenceField
  value: string
  onChange: (value: string) => void
}) {
  const { t } = useI18n()

  // One attribute name can mean two things: `default` is the registry's
  // default value and a printer's "set as default", `name` is a registry
  // value, an environment variable and a printer all at once. A label for the
  // kind wins where there is one; `t` gives the key back when there is not.
  const specific = `pref.field.${kindId}.${field.name}` as MessageKey
  const perKind = t(specific)
  const label = perKind === specific ? t(`pref.field.${field.name}` as MessageKey) : perKind

  if (field.kind === 'bool') {
    return (
      <label className="checkbox">
        <input
          type="checkbox"
          checked={value === '1'}
          onChange={(event) => onChange(event.target.checked ? '1' : '0')}
        />
        <span>{label}</span>
      </label>
    )
  }

  if (field.kind === 'choice') {
    return (
      <label className="field">
        <span className="field__label">{label}</span>
        <select value={value} onChange={(event) => onChange(event.target.value)}>
          {field.choices.map((choice) => (
            <option key={choice} value={choice}>
              {/* Hives and registry types are spelled the way the registry
                  spells them; the rest get a word. */}
              {choice.startsWith('HKEY_') || choice.startsWith('REG_')
                ? choice
                : t(`pref.choice.${choice}` as MessageKey)}
            </option>
          ))}
        </select>
      </label>
    )
  }

  return (
    <label className="field">
      <span className="field__label">{label}</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  )
}
