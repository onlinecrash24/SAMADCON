/**
 * Security settings — computer configuration only.
 *
 * Six groups on the left, their settings on the right, the way the Windows
 * editor arranges them. That arrangement is not the file's: password and
 * lockout policy share the ``[System Access]`` section, and nobody thinks of
 * them as one thing.
 *
 * What a setting *is* comes from the catalogue rather than from here — the
 * file is all text, so minutes, switches and the four audit states are
 * knowledge the server holds. Anything present in the file that the catalogue
 * does not name is still shown, because a policy that configures something we
 * do not recognise is exactly the case worth seeing.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../../api/endpoints'
import type {
  DirectoryObject,
  Gpo,
  SecuritySetting,
  SecurityTrustee,
} from '../../../api/types'
import { ErrorMessage, Spinner } from '../../../components/primitives'
import { ObjectPicker } from '../../directory/ObjectPicker'
import { useI18n } from '../../../i18n'
import type { MessageKey } from '../../../i18n/messages'

const GROUP_ORDER = ['password', 'lockout', 'kerberos', 'audit', 'rights', 'restricted_groups']

/** Not configured is an absent key, not a zero. */
const UNSET = ''

export function SecurityTab({
  gpo,
  onChanged,
}: {
  gpo: Gpo
  onChanged: (message: string) => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const [group, setGroup] = useState('password')
  const [error, setError] = useState<unknown>(null)

  const catalogue = useQuery({
    queryKey: ['security-catalogue'],
    queryFn: () => api.securityCatalogue(),
  })
  const current = useQuery({
    queryKey: ['gpo-security', gpo.dn],
    queryFn: () => api.gpoSecurity(gpo.dn),
  })

  // Its own mutation: a restricted group is two keys, and the server clears
  // both in one write. Routing it through `save`, which sends one key, would
  // need two calls — and the first raises the version, so the second is
  // refused as somebody else's change.
  const groupChange = useMutation({
    mutationFn: (payload: { sid: string; present: boolean }) =>
      api.setRestrictedGroup(gpo.dn, {
        ...payload,
        expected_version: current.data?.version_number,
      }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['gpo-security', gpo.dn] })
      onChanged(result.changed ? t('security.saved') : t('security.unchanged'))
    },
    onError: setError,
  })

  const save = useMutation({
    mutationFn: (payload: { section: string; key: string; value: string | string[] | null }) =>
      api.setGpoSecurity(gpo.dn, {
        ...payload,
        expected_version: current.data?.version_number,
      }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['gpo-security', gpo.dn] })
      onChanged(result.changed ? t('security.saved') : t('security.unchanged'))
    },
    onError: setError,
  })

  if (catalogue.isLoading || current.isLoading) return <Spinner label={t('status.loading')} />
  if (catalogue.error) return <ErrorMessage error={catalogue.error} />
  if (current.error) return <ErrorMessage error={current.error} />

  const settings = catalogue.data?.settings ?? []
  const sections = current.data?.sections ?? {}

  const valueOf = (setting: SecuritySetting): string => {
    const raw = sections[setting.section]?.[setting.key]
    return typeof raw === 'string' ? raw : UNSET
  }

  const trusteesOf = (section: string, key: string): SecurityTrustee[] => {
    const raw = sections[section]?.[key]
    return Array.isArray(raw) ? raw : []
  }

  const groups = GROUP_ORDER.filter((id) =>
    id === 'restricted_groups' ? true : settings.some((item) => item.group === id),
  )

  return (
    <div className="gpedit">
      {/* The same trap as everywhere else: written, applied by nobody. */}
      {!current.data?.registered && current.data?.present && (
        <div className="alert alert--warning">{t('security.notRegistered')}</div>
      )}

      <div className="gpedit__panes">
        <nav className="gpedit__tree" aria-label={t('security.groups')}>
          <ul className="cats">
            {groups.map((id) => (
              <li key={id}>
                <button
                  type="button"
                  className={group === id ? 'cats__node cats__node--active' : 'cats__node'}
                  onClick={() => setGroup(id)}
                >
                  <span className="cats__name">{t(`security.group.${id}` as MessageKey)}</span>
                  <Configured
                    count={countConfigured(id, settings, sections, catalogue.data?.restricted_groups)}
                  />
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <section className="gpedit__list">
          <ErrorMessage error={error} onDismiss={() => setError(null)} />

          {group === 'restricted_groups' ? (
            <RestrictedGroups
              onGroup={(sid, present) => groupChange.mutate({ sid, present })}
              section={catalogue.data!.restricted_groups.section}
              suffixes={catalogue.data!.restricted_groups}
              entries={sections[catalogue.data!.restricted_groups.section] ?? {}}
              busy={save.isPending}
              onSave={(section, key, value) => save.mutate({ section, key, value })}
            />
          ) : group === 'rights' ? (
            <UserRights
              settings={settings.filter((item) => item.group === 'rights')}
              trusteesOf={trusteesOf}
              busy={save.isPending}
              onSave={(section, key, value) => save.mutate({ section, key, value })}
            />
          ) : (
            <PlainSettings
              settings={settings.filter((item) => item.group === group)}
              valueOf={valueOf}
              busy={save.isPending}
              onSave={(section, key, value) => save.mutate({ section, key, value })}
            />
          )}
        </section>
      </div>
    </div>
  )
}

function Configured({ count }: { count: number }) {
  if (count === 0) return null
  return <span className="muted small">{count}</span>
}

function countConfigured(
  group: string,
  settings: SecuritySetting[],
  sections: Record<string, Record<string, unknown>>,
  restricted?: { section: string },
): number {
  if (group === 'restricted_groups') {
    return Object.keys(sections[restricted?.section ?? ''] ?? {}).length
  }
  return settings.filter(
    (item) => item.group === group && sections[item.section]?.[item.key] !== undefined,
  ).length
}

// ---------------------------------------------------------------------------

/** Numbers, switches and the audit categories — everything with one value. */
function PlainSettings({
  settings,
  valueOf,
  busy,
  onSave,
}: {
  settings: SecuritySetting[]
  valueOf: (setting: SecuritySetting) => string
  busy: boolean
  onSave: (section: string, key: string, value: string | null) => void
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState<Record<string, string>>({})

  const shown = (setting: SecuritySetting) => draft[setting.key] ?? valueOf(setting)

  return (
    <div className="table-wrap">
      <table className="table table--compact">
        <thead>
          <tr>
            <th>{t('security.setting')}</th>
            {/* Not `table__cell--narrow`: that is width 1%, which is right for
                a label and wrong for anything holding an input. */}
            <th className="table__cell--value">{t('security.value')}</th>
            <th className="table__cell--narrow" />
          </tr>
        </thead>
        <tbody>
          {settings.map((setting) => (
            <tr key={setting.key}>
              <td>
                <strong>{t(`security.key.${setting.key}` as MessageKey)}</strong>
                <div className="muted small mono">{setting.key}</div>
              </td>
              <td>
                <SettingInput
                  setting={setting}
                  value={shown(setting)}
                  onChange={(value) => setDraft({ ...draft, [setting.key]: value })}
                />
              </td>
              <td>
                <div className="pane__actions">
                  <button
                    type="button"
                    className="button"
                    disabled={busy || shown(setting) === valueOf(setting)}
                    onClick={() =>
                      onSave(setting.section, setting.key, shown(setting) || null)
                    }
                  >
                    {t('action.save')}
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SettingInput({
  setting,
  value,
  onChange,
}: {
  setting: SecuritySetting
  value: string
  onChange: (value: string) => void
}) {
  const { t } = useI18n()

  if (setting.kind === 'switch' || setting.kind === 'audit') {
    const options =
      setting.kind === 'switch'
        ? ['0', '1']
        : ['0', '1', '2', '3'] // none, success, failure, both
    return (
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value={UNSET}>{t('security.notDefined')}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {t(`security.${setting.kind}.${option}` as MessageKey)}
          </option>
        ))}
      </select>
    )
  }

  return (
    <div className="field-inline">
      <input
        type="number"
        min={setting.min ?? undefined}
        max={setting.max ?? undefined}
        value={value}
        placeholder={t('security.notDefined')}
        onChange={(event) => onChange(event.target.value)}
      />
      {setting.unit && (
        <span className="muted small">{t(`security.unit.${setting.unit}` as MessageKey)}</span>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------

/** User rights: one list of accounts each. */
function UserRights({
  settings,
  trusteesOf,
  busy,
  onSave,
}: {
  settings: SecuritySetting[]
  trusteesOf: (section: string, key: string) => SecurityTrustee[]
  busy: boolean
  onSave: (section: string, key: string, value: string[] | null) => void
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState<string | null>(null)

  return (
    <div className="stack-tight">
      <p className="muted small">{t('security.rightsHint')}</p>

      {settings.map((setting) => {
        const trustees = trusteesOf(setting.section, setting.key)
        return (
          <div key={setting.key} className="card">
            <h4>{t(`security.key.${setting.key}` as MessageKey)}</h4>
            <div className="muted small mono">{setting.key}</div>

            <TrusteeList
              trustees={trustees}
              busy={busy}
              onRemove={(sid) =>
                onSave(
                  setting.section,
                  setting.key,
                  keep(trustees, sid).length ? keep(trustees, sid) : null,
                )
              }
            />

            {open === setting.key ? (
              <ObjectPicker
                types={['user', 'group', 'computer']}
                exclude={new Set(trustees.map((item) => (item.dn ?? '').toLowerCase()))}
                onSelect={(object: DirectoryObject) => {
                  setOpen(null)
                  if (!object.sid) return
                  onSave(setting.section, setting.key, [
                    ...trustees.map((item) => item.sid),
                    object.sid,
                  ])
                }}
              />
            ) : (
              <button type="button" className="button" onClick={() => setOpen(setting.key)}>
                + {t('security.addAccount')}
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}

function keep(trustees: SecurityTrustee[], sid: string): string[] {
  return trustees.filter((item) => item.sid !== sid).map((item) => item.sid)
}

function TrusteeList({
  trustees,
  busy,
  onRemove,
}: {
  trustees: SecurityTrustee[]
  busy: boolean
  onRemove: (sid: string) => void
}) {
  const { t } = useI18n()

  if (trustees.length === 0) return <p className="muted small">{t('security.notDefined')}</p>

  return (
    <ul className="plain-list">
      {trustees.map((trustee) => (
        <li key={trustee.sid}>
          <span>{trustee.name}</span> <span className="muted small mono">{trustee.sid}</span>{' '}
          <button
            type="button"
            className="link"
            disabled={busy}
            onClick={() => onRemove(trustee.sid)}
          >
            {t('action.remove')}
          </button>
        </li>
      ))}
    </ul>
  )
}

// ---------------------------------------------------------------------------

/**
 * Restricted groups: no fixed list. Each group named here gets two keys —
 * who belongs to it, and what it belongs to.
 */
function RestrictedGroups({
  section,
  suffixes,
  entries,
  busy,
  onSave,
  onGroup,
}: {
  section: string
  suffixes: { members_suffix: string; memberof_suffix: string }
  entries: Record<string, string | SecurityTrustee[]>
  busy: boolean
  onSave: (section: string, key: string, value: string[] | null) => void
  onGroup: (sid: string, present: boolean) => void
}) {
  const { t } = useI18n()
  const [adding, setAdding] = useState(false)
  const [open, setOpen] = useState<string | null>(null)

  const groups = new Set<string>()
  for (const key of Object.keys(entries)) {
    for (const suffix of [suffixes.members_suffix, suffixes.memberof_suffix]) {
      if (key.endsWith(suffix)) groups.add(key.slice(0, -suffix.length))
    }
  }

  const membersOf = (group: string): SecurityTrustee[] => {
    const raw = entries[`${group}${suffixes.members_suffix}`]
    return Array.isArray(raw) ? raw : []
  }

  return (
    <div className="stack-tight">
      <p className="muted small">{t('security.restrictedHint')}</p>

      {[...groups].map((group) => {
        const members = membersOf(group)
        const key = `${group}${suffixes.members_suffix}`
        return (
          <div key={group} className="card">
            <div className="field-inline">
              <h4 className="mono small">{group}</h4>
              <button
                type="button"
                className="button button--danger"
                disabled={busy}
                onClick={() => onGroup(group, false)}
              >
                {t('security.removeGroup')}
              </button>
            </div>
            <TrusteeList
              trustees={members}
              busy={busy}
              onRemove={(sid) =>
                onSave(section, key, keep(members, sid).length ? keep(members, sid) : null)
              }
            />
            {open === group ? (
              <ObjectPicker
                types={['user', 'group', 'computer']}
                onSelect={(object: DirectoryObject) => {
                  setOpen(null)
                  if (!object.sid) return
                  onSave(section, key, [...members.map((item) => item.sid), object.sid])
                }}
              />
            ) : (
              <button type="button" className="button" onClick={() => setOpen(group)}>
                + {t('security.addAccount')}
              </button>
            )}
          </div>
        )
      })}

      {adding ? (
        <div className="card">
          <ObjectPicker
            types={['group']}
            label="security.restrictedGroup"
            onSelect={(object: DirectoryObject) => {
              setAdding(false)
              if (!object.sid) return
              onGroup(`*${object.sid}`, true)
            }}
          />
        </div>
      ) : (
        <button type="button" className="button" onClick={() => setAdding(true)}>
          + {t('security.addGroup')}
        </button>
      )}
    </div>
  )
}
