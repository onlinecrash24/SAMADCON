/**
 * Group policy preferences — GPMC's "Einstellungen" branch, one tab per
 * sub-branch: Windows Settings and Control Panel Settings (preferenceAreas.ts).
 *
 * Laid out as GPMC lays it out: a list of the items of one type — name,
 * order, action and the one thing that tells them apart — and each item opened
 * in a window with two tabs, "General" and "Common". The items used to be
 * forms one under the other, which read as clutter once a type had more than
 * two. Every change is saved at once, the whole list as the file holds it:
 * OK in the window, a move, a delete. There is no separate save to forget.
 *
 * The form comes from the server's catalogue rather than from here, down to
 * which fields exist and which values a choice offers. Adding a preference
 * type is then a change in one Python file — this tab needs a label and
 * nothing else.
 *
 * Two things the editor handles with care:
 *
 * * **Item-level targeting.** Group, OU, user and computer conditions are
 *   edited (TargetingEditor.tsx); anything else — a collection, an IP range,
 *   WMI — is displayed and left alone, and nothing about it is sent back. A
 *   dropped filter widens who a drive is mapped for, silently.
 * * **A stored password.** The key for `cpassword` has been public since 2014.
 *   An item that has one keeps it; nothing here can add one.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { api } from '../../../api/endpoints'
import type {
  DirectoryObject,
  Gpo,
  PreferenceAction,
  PreferenceField,
  PreferenceKind,
  PreferenceMember,
  PreferenceTypeId,
} from '../../../api/types'
import { anchorOf, useContextMenu, type MenuNode } from '../../../components/ContextMenu'
import { ErrorMessage, Modal, Spinner } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import { useSession } from '../../../state/session'
import { ObjectPicker } from '../../directory/ObjectPicker'
import type { MessageKey } from '../../../i18n/messages'
import { choiceLabel, choicesWithCurrent } from './fieldChoices'
import { FIRST_TYPE, type PreferenceArea, typesIn } from './preferenceAreas'
import {
  blank,
  type Draft,
  itemSummary,
  moved,
  toDraft,
  toPayload,
  withItem,
  without,
} from './preferenceList'
import { rowCommand } from './rowKeys'
import { OptionsEditor, TargetingEditor } from './TargetingEditor'

const HALVES = ['Machine', 'User'] as const
const MULTI_SZ = 'REG_MULTI_SZ'

export function PreferencesTab({
  gpo,
  area,
  onChanged,
}: {
  gpo: Gpo
  area: PreferenceArea
  onChanged: (message: string) => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const menu = useContextMenu()

  const [selected, setSelected] = useState<{ type: PreferenceTypeId; half: string }>({
    type: FIRST_TYPE[area],
    half: 'Machine',
  })
  const [row, setRow] = useState<number | null>(null)
  const [editing, setEditing] = useState<{ index: number | null; draft: Draft } | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)
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
  const list = useMemo(() => (items ?? []).map(toDraft), [items])

  const save = useMutation({
    mutationFn: (next: Draft[]) =>
      api.setGpoPreferences(gpo.dn, {
        type: selected.type,
        half: selected.half,
        items: toPayload(next),
        expected_version: current.data?.version_number,
      }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['gpo-preferences', gpo.dn] })
      setEditing(null)
      setDeleting(null)
      setError(null)
      onChanged(result.changed ? t('pref.saved') : t('pref.unchanged'))
    },
    onError: setError,
  })

  if (catalogue.isLoading || current.isLoading) return <Spinner label={t('status.loading')} />
  if (catalogue.error) return <ErrorMessage error={catalogue.error} />
  if (current.error) return <ErrorMessage error={current.error} />

  const types = typesIn(area, catalogue.data?.types ?? [])
  const actions = catalogue.data?.actions ?? []
  const type = types.find((item) => item.id === selected.type)
  // Printers are the only type where this is more than one; "New" then
  // offers one entry per kind.
  const kinds = (type?.kinds ?? []).filter((kind) => kind.halves.includes(selected.half))
  const creatable = kinds.filter((kind) => kind.creatable)

  const select = (next: { type: PreferenceTypeId; half: string }) => {
    setSelected(next)
    setRow(null)
    setError(null)
  }
  const open = (index: number) => {
    const draft = list[index]
    if (draft) setEditing({ index, draft })
  }
  const move = (index: number, delta: number) => {
    const next = moved(list, index, delta)
    if (next === list) return
    setRow(index + delta)
    save.mutate(next)
  }

  const newEntries: MenuNode[] =
    creatable.length === 1
      ? [{ id: `new:${creatable[0]?.id}`, labelKey: 'pref.menu.new' }]
      : creatable.length > 1
        ? [
            {
              id: 'new',
              labelKey: 'pref.menu.new',
              children: creatable.map((kind) => ({
                id: `new:${kind.id}`,
                labelKey: `pref.kind.${kind.id}` as MessageKey,
              })),
            },
          ]
        : []
  const openNew = (id: string) => {
    const kind = creatable.find((entry) => `new:${entry.id}` === id)
    if (kind) setEditing({ index: null, draft: blank(kind) })
  }

  const rowMenu = (index: number, at: { x: number; y: number }) => {
    setRow(index)
    menu.open(
      at,
      [
        { id: 'properties', labelKey: 'pref.menu.properties' },
        ...newEntries,
        'separator',
        { id: 'up', labelKey: 'pref.menu.up' },
        { id: 'down', labelKey: 'pref.menu.down' },
        'separator',
        { id: 'delete', labelKey: 'pref.menu.delete', danger: true },
      ],
      (id) => {
        if (id === 'properties') open(index)
        else if (id === 'up') move(index, -1)
        else if (id === 'down') move(index, 1)
        else if (id === 'delete') setDeleting(index)
        else openNew(id)
      },
    )
  }

  const kindOf = (draft: Draft) => kinds.find((entry) => entry.id === draft.kind) ?? kinds[0]

  return (
    <div className="gpedit">
      <div className="gpedit__panes">
        <nav
          className="gpedit__tree"
          aria-label={t(area === 'windows' ? 'gpo.tab.prefWindows' : 'gpo.tab.prefControlPanel')}
        >
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
                        onClick={() => select({ type: item.id, half })}
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

        <section
          className="gpedit__list"
          onContextMenu={(event) => {
            if (newEntries.length === 0) return
            event.preventDefault()
            menu.open({ x: event.clientX, y: event.clientY }, newEntries, openNew)
          }}
        >
          {!editing && <ErrorMessage error={error} onDismiss={() => setError(null)} />}

          <p className="muted small">{t(`pref.hint.${selected.type}` as MessageKey)}</p>

          <div className="pane__actions">
            {creatable.map((kind) => (
              <button
                key={kind.id}
                type="button"
                className="button"
                onClick={() => setEditing({ index: null, draft: blank(kind) })}
              >
                + {creatable.length > 1 ? t(`pref.kind.${kind.id}` as MessageKey) : t('pref.menu.new')}
              </button>
            ))}
          </div>

          {list.length === 0 ? (
            <p className="muted">{t('pref.none')}</p>
          ) : (
            <div className="table-wrap">
              <table className="table table--compact pref__list">
                <thead>
                  <tr>
                    <th>{t('pref.column.name')}</th>
                    <th className="table__cell--narrow">{t('pref.column.order')}</th>
                    <th className="table__cell--narrow">{t('pref.action')}</th>
                    <th>{t(`pref.column.${selected.type}` as MessageKey)}</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((draft, index) => (
                    <tr
                      key={draft.uid ?? index}
                      tabIndex={0}
                      className={row === index ? 'table__row--selected' : undefined}
                      onClick={() => setRow(index)}
                      onDoubleClick={() => open(index)}
                      onContextMenu={(event) => {
                        event.preventDefault()
                        event.stopPropagation()
                        rowMenu(index, { x: event.clientX, y: event.clientY })
                      }}
                      onKeyDown={(event) => {
                        const command = rowCommand(event)
                        if (command === 'open') open(index)
                        else if (command === 'delete') setDeleting(index)
                        else if (command === 'menu') rowMenu(index, anchorOf(event.currentTarget))
                      }}
                    >
                      <td>
                        {draft.name || t('pref.newItem')}
                        {(draft.targeting === null || draft.targeting.length > 0) && (
                          <span className="badge badge--muted pref__targeted" title={t('pref.targeted')}>
                            {t('pref.targeting')}
                          </span>
                        )}
                        {kinds.length > 1 && (
                          <div className="muted small">
                            {t(`pref.kind.${draft.kind}` as MessageKey)}
                          </div>
                        )}
                      </td>
                      <td className="table__cell--narrow">{index + 1}</td>
                      <td className="table__cell--narrow">
                        {draft.action ? t(`pref.action.${draft.action}` as MessageKey) : ''}
                      </td>
                      <td className="mono small">{itemSummary(draft.kind, draft.properties)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {menu.menu}
        </section>
      </div>

      {editing && (() => {
        const kind = kindOf(editing.draft)
        if (!kind) return null
        return (
          <ItemDialog
            type={selected.type}
            half={selected.half}
            kind={kind}
            showKind={kinds.length > 1}
            actions={actions}
            item={editing.draft}
            saving={save.isPending}
            error={error}
            onChange={(change) => setEditing({ ...editing, draft: { ...editing.draft, ...change } })}
            onClose={() => {
              setEditing(null)
              setError(null)
            }}
            onOk={() => save.mutate(withItem(list, editing.index, editing.draft))}
          />
        )
      })()}

      {deleting !== null && list[deleting] && (
        <Modal
          title={t('pref.delete.title', { name: list[deleting]?.name || t('pref.newItem') })}
          onClose={() => setDeleting(null)}
          footer={
            <>
              <button type="button" className="button" onClick={() => setDeleting(null)}>
                {t('action.cancel')}
              </button>
              <button
                type="button"
                className="button button--danger"
                disabled={save.isPending}
                onClick={() => save.mutate(without(list, deleting))}
              >
                {t('pref.menu.delete')}
              </button>
            </>
          }
        >
          <ErrorMessage error={error} />
          <p>{t('pref.delete.body')}</p>
        </Modal>
      )}
    </div>
  )
}

function Count({ count }: { count: number }) {
  if (!count) return null
  return <span className="muted small">{count}</span>
}

/**
 * One item in its own window, with GPMC's two tabs: what the item does, and
 * the options and targeting every item has.
 */
function ItemDialog({
  type,
  half,
  kind,
  showKind,
  actions,
  item,
  saving,
  error,
  onChange,
  onClose,
  onOk,
}: {
  type: PreferenceTypeId
  half: string
  kind: PreferenceKind
  showKind: boolean
  actions: PreferenceAction[]
  item: Draft
  saving: boolean
  error: unknown
  onChange: (change: Partial<Draft>) => void
  onClose: () => void
  onOk: () => void
}) {
  const { t } = useI18n()
  const [tab, setTab] = useState<'general' | 'common'>('general')
  const title = showKind
    ? `${item.name || t('pref.newItem')} — ${t(`pref.kind.${kind.id}` as MessageKey)}`
    : item.name || t('pref.newItem')

  return (
    <Modal
      title={title}
      wide
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button type="button" className="button button--primary" disabled={saving} onClick={onOk}>
            {t('action.ok')}
          </button>
        </>
      }
    >
      <div className="tabs">
        {(['general', 'common'] as const).map((id) => (
          <button
            key={id}
            type="button"
            className={tab === id ? 'tabs__tab tabs__tab--active' : 'tabs__tab'}
            onClick={() => setTab(id)}
          >
            {t(`pref.tab.${id}` as MessageKey)}
          </button>
        ))}
      </div>
      <div className="form">
        <ErrorMessage error={error} />
        {tab === 'general' ? (
          <GeneralFields type={type} kind={kind} actions={actions} item={item} onChange={onChange} />
        ) : (
          <>
            <OptionsEditor
              half={half}
              options={item.options}
              action={item.action}
              hasAction={kind.has_action}
              targetingEditable={item.targeting !== null}
              onChange={(options, action) => onChange({ options, action })}
            />
            <TargetingEditor
              conditions={item.targeting}
              filterNames={item.filter_names}
              onChange={(targeting) => onChange({ targeting })}
            />
          </>
        )}
      </div>
    </Modal>
  )
}

function GeneralFields({
  type,
  kind,
  actions,
  item,
  onChange,
}: {
  type: PreferenceTypeId
  kind: PreferenceKind
  actions: PreferenceAction[]
  item: Draft
  onChange: (change: Partial<Draft>) => void
}) {
  const { t } = useI18n()
  const setProperty = (name: string, value: string) =>
    onChange({ properties: { ...item.properties, [name]: value } })

  // The lines of a REG_MULTI_SZ live in their own block, not in the value
  // attribute, so the value box turns into a text area for that one type.
  const multiLine = type === 'registry' && item.properties.type === MULTI_SZ

  return (
    <>
      {kind.has_action && (
        <label className="field">
          <span className="field__label">{t('pref.action')}</span>
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
        </label>
      )}

      {item.has_password && <div className="alert alert--warning">{t('pref.password')}</div>}
      {!kind.creatable && <div className="alert alert--info">{t('pref.notCreatable')}</div>}

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
        <Members members={item.members ?? []} onChange={(members) => onChange({ members })} />
      )}
    </>
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
          {choicesWithCurrent(field.choices, value).map((choice) => (
            <option key={choice} value={choice}>
              {choiceLabel(field.name, choice, (key) => t(key as MessageKey))}
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
