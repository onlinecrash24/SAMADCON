/**
 * Samba's own group policies — the ones `samba-gpupdate` applies on Linux
 * domain members.
 *
 * **Windows clients ignore these entirely.** That is the first thing anyone
 * looking at an empty `gpresult` needs to know, so the tab says it rather
 * than leaving it to be discovered. The proof for these runs through
 * `samba-gpupdate --rsop` on a member, not through a Windows report.
 *
 * Each kind has its own entry shape, so each gets its own editor. What they
 * share is that the manifest holds the whole list: saving sends it as it
 * should end up, which makes reordering and removing the same operation as
 * adding.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { api } from '../../../api/endpoints'
import type { Gpo, VgpEntry, VgpKind, VgpPolicy } from '../../../api/types'
import { ErrorMessage, Spinner } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import type { MessageKey } from '../../../i18n/messages'

/** One block of text rather than a list. */
const TEXT_KINDS: VgpPolicy[] = ['motd', 'issue']

export function VgpTab({ gpo, onChanged }: { gpo: Gpo; onChanged: (message: string) => void }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const [policy, setPolicy] = useState<VgpPolicy>('sudoers')
  const [draft, setDraft] = useState<VgpEntry[]>([])
  const [error, setError] = useState<unknown>(null)

  const kinds = useQuery({ queryKey: ['vgp-kinds'], queryFn: () => api.vgpKinds() })
  const current = useQuery({
    queryKey: ['gpo-vgp', gpo.dn],
    queryFn: () => api.gpoVgp(gpo.dn),
  })

  useEffect(() => {
    setDraft(current.data?.policies?.[policy]?.entries ?? [])
  }, [current.data, policy])

  const save = useMutation({
    mutationFn: () =>
      api.setGpoVgp(gpo.dn, {
        policy,
        entries: draft,
        expected_version: current.data?.version_number,
      }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['gpo-vgp', gpo.dn] })
      onChanged(result.changed ? t('vgp.saved') : t('vgp.unchanged'))
    },
    onError: setError,
  })

  if (kinds.isLoading || current.isLoading) return <Spinner label={t('status.loading')} />
  if (kinds.error) return <ErrorMessage error={kinds.error} />
  if (current.error) return <ErrorMessage error={current.error} />

  const kind = (kinds.data?.kinds ?? []).find((item) => item.id === policy)

  return (
    <div className="gpedit">
      {/* The Linux surface is split by mechanism, not by intent: these come
          from manifests, while Samba's registry-based policies — smb.conf, the
          Unix cron scripts, sudo rights — sit under administrative templates,
          because that is what they are. Pointing at the other half beats
          letting someone conclude the tool only does this one. */}
      <div className="alert alert--info">
        {t('vgp.linuxOnly')} {t('vgp.alsoUnderAdmx')}
      </div>

      <div className="gpedit__panes">
        <nav className="gpedit__tree" aria-label={t('vgp.policies')}>
          <ul className="cats">
            {(kinds.data?.kinds ?? []).map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className={policy === item.id ? 'cats__node cats__node--active' : 'cats__node'}
                  onClick={() => setPolicy(item.id)}
                >
                  <span className="cats__name">{t(`vgp.kind.${item.id}` as MessageKey)}</span>
                  <Count entries={current.data?.policies?.[item.id]?.entries} />
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <section className="gpedit__list">
          <ErrorMessage error={error} onDismiss={() => setError(null)} />

          {kind && <PolicyHeading kind={kind} />}

          {/* Samba ships two sudoers appliers — vgp_sudoers_ext reads this
              manifest, gp_sudoers_ext reads registry policy — and a member
              running both gets rules from both. Nothing warns about that
              anywhere else, so this does. */}
          {policy === 'sudoers' && (
            <div className="alert alert--warning">{t('vgp.sudoersDuplicated')}</div>
          )}

          {TEXT_KINDS.includes(policy) ? (
            <TextEditor
              value={String(draft[0]?.text ?? '')}
              onChange={(text) => setDraft(text ? [{ text }] : [])}
            />
          ) : (
            <EntryTable policy={policy} entries={draft} onChange={setDraft} />
          )}

          <div className="pane__actions">
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

function Count({ entries }: { entries?: VgpEntry[] }) {
  if (!entries || entries.length === 0) return null
  return <span className="muted small">{entries.length}</span>
}

function PolicyHeading({ kind }: { kind: VgpKind }) {
  const { t } = useI18n()
  return (
    <div className="stack-tight">
      <p className="muted small">{t(`vgp.hint.${kind.id}` as MessageKey)}</p>
      <p className="muted small mono">{kind.path}</p>
    </div>
  )
}

function TextEditor({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const { t } = useI18n()
  return (
    <label className="field">
      <span className="field__label">{t('vgp.text')}</span>
      <textarea rows={10} value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  )
}

/** Which fields each kind carries, in the order they are shown. */
const FIELDS: Record<string, { key: string; wide?: boolean }[]> = {
  sudoers: [{ key: 'command', wide: true }, { key: 'user' }, { key: 'principals', wide: true }],
  symlink: [{ key: 'source', wide: true }, { key: 'target', wide: true }],
  openssh: [{ key: 'key' }, { key: 'value', wide: true }],
  access_allow: [{ key: 'name' }, { key: 'domain' }],
  access_deny: [{ key: 'name' }, { key: 'domain' }],
}

const BLANK: Record<string, VgpEntry> = {
  sudoers: { command: 'ALL', user: 'ALL', principals: [], password: false },
  symlink: { source: '', target: '' },
  openssh: { key: '', value: '' },
  access_allow: { name: '', domain: '' },
  access_deny: { name: '', domain: '' },
}

function EntryTable({
  policy,
  entries,
  onChange,
}: {
  policy: VgpPolicy
  entries: VgpEntry[]
  onChange: (entries: VgpEntry[]) => void
}) {
  const { t } = useI18n()
  const fields = FIELDS[policy] ?? []

  const edit = (index: number, key: string, value: unknown) =>
    onChange(entries.map((entry, at) => (at === index ? { ...entry, [key]: value } : entry)))

  return (
    <>
      <div className="table-wrap">
        <table className="table table--compact">
          <thead>
            <tr>
              {fields.map((field) => (
                <th key={field.key}>{t(`vgp.field.${field.key}` as MessageKey)}</th>
              ))}
              {policy === 'sudoers' && (
                <th className="table__cell--narrow">{t('vgp.field.password')}</th>
              )}
              <th className="table__cell--narrow" />
            </tr>
          </thead>
          <tbody>
            {entries.map((entry, index) => (
              <tr key={index}>
                {fields.map((field) => (
                  <td key={field.key}>
                    <input
                      value={
                        field.key === 'principals'
                          ? ((entry.principals as string[]) ?? []).join(', ')
                          : String(entry[field.key] ?? '')
                      }
                      placeholder={
                        field.key === 'principals' ? t('vgp.principalsPlaceholder') : undefined
                      }
                      onChange={(event) =>
                        edit(
                          index,
                          field.key,
                          field.key === 'principals'
                            ? event.target.value
                                .split(',')
                                .map((item) => item.trim())
                                .filter(Boolean)
                            : event.target.value,
                        )
                      }
                    />
                  </td>
                ))}
                {policy === 'sudoers' && (
                  <td>
                    <label className="checkbox checkbox--inline">
                      <input
                        type="checkbox"
                        checked={Boolean(entry.password)}
                        onChange={(event) => edit(index, 'password', event.target.checked)}
                      />
                      <span>{t('vgp.field.password')}</span>
                    </label>
                  </td>
                )}
                <td>
                  <button
                    type="button"
                    className="button button--danger"
                    onClick={() => onChange(entries.filter((_, at) => at !== index))}
                  >
                    {t('action.remove')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {entries.length === 0 && <p className="muted">{t('vgp.none')}</p>}

      <div className="pane__actions">
        <button
          type="button"
          className="button"
          onClick={() => onChange([...entries, { ...(BLANK[policy] ?? {}) }])}
        >
          + {t('vgp.add')}
        </button>
      </div>
    </>
  )
}
