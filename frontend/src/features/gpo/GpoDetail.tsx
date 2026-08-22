/**
 * One policy: where it is linked, who it applies to, and whether its two
 * halves agree.
 *
 * That last tab is the one GPMC does not have. A policy whose GPT.INI version
 * disagrees with the directory is either never re-read by clients or re-read
 * forever, and nothing else in any console says so.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import type { Gpo } from '../../api/types'
import { Badge, ErrorMessage, Modal, Spinner, useDateFormat } from '../../components/primitives'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n/messages'
import { CopyGpoDialog, DeleteGpoDialog } from './GpoDialogs'
import { ReportTab } from './ReportTab'
import { WmiTab } from './WmiTab'
import { AdmxTab } from './admx/AdmxTab'
import { RedirectionTab } from './redirection/RedirectionTab'
import { SecurityTab } from './security/SecurityTab'
import { PreferencesTab } from './preferences/PreferencesTab'
import { VgpTab } from './vgp/VgpTab'
import { ScriptsTab } from './scripts/ScriptsTab'

type Tab =
  | 'general'
  | 'templates'
  | 'scripts'
  | 'redirection'
  | 'security'
  | 'vgp'
  | 'preferences'
  | 'settings'
  | 'links'
  | 'filtering'
  | 'wmi'
  | 'health'

interface GpoDetailProps {
  gpo: Gpo
  onClose: () => void
  onChanged: (message: string) => void
  onDeleted: () => void
}

export function GpoDetail({ gpo, onClose, onChanged, onDeleted }: GpoDetailProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const [tab, setTab] = useState<Tab>('general')
  const [error, setError] = useState<unknown>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [copying, setCopying] = useState(false)

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['gpo', gpo.dn] })
  }

  return (
    // No frame of its own any more. This is the content of a window now, and
    // the window supplies the title bar, the position and the close button —
    // which is what lets two policies stand open side by side.
    <div className="sheet-window">
      <div className="tabs">
        {(
          [
            'general',
            'templates',
            'scripts',
            'redirection',
            'security',
            'vgp',
            'preferences',
            'settings',
            'links',
            'filtering',
            'wmi',
            'health',
          ] as Tab[]
        ).map((id) => (
          <button
            key={id}
            type="button"
            className={tab === id ? 'tabs__tab tabs__tab--active' : 'tabs__tab'}
            onClick={() => setTab(id)}
          >
            {t(`gpo.tab.${id}` as MessageKey)}
          </button>
        ))}
      </div>

      {/* Everything below the tabs scrolls; the tabs themselves do not. A tab
          with a long list — the settings report, the folder table — otherwise
          pushes the row out of the window, and there is no way back to it. */}
      <div className="sheet-window__panel sheet-window__panel--fill">
        <ErrorMessage error={error} onDismiss={() => setError(null)} />

        {tab === 'general' && (
          <GeneralTab
            gpo={gpo}
            onChanged={(message) => {
              refresh()
              onChanged(message)
            }}
          />
        )}
        {tab === 'templates' && <AdmxTab gpo={gpo} onChanged={onChanged} />}
        {tab === 'scripts' && <ScriptsTab gpo={gpo} onChanged={onChanged} />}
        {tab === 'redirection' && <RedirectionTab gpo={gpo} onChanged={onChanged} />}
        {tab === 'security' && <SecurityTab gpo={gpo} onChanged={onChanged} />}
        {tab === 'vgp' && <VgpTab gpo={gpo} onChanged={onChanged} />}
        {tab === 'preferences' && <PreferencesTab gpo={gpo} onChanged={onChanged} />}
        {tab === 'settings' && <ReportTab gpo={gpo} />}
        {tab === 'links' && (
          <LinksTab
            gpo={gpo}
            onChanged={(message) => {
              refresh()
              onChanged(message)
            }}
          />
        )}
        {tab === 'filtering' && <FilteringTab gpo={gpo} />}
        {tab === 'wmi' && <WmiTab gpo={gpo} onChanged={onChanged} />}
        {tab === 'health' && <HealthTab gpo={gpo} />}
      </div>

      {/* Below the scrolling panel, so it stays reachable however long the
          settings report gets. */}
      <div className="sheet-window__footer">
        <button
          type="button"
          className="button button--danger"
          onClick={() => setConfirmDelete(true)}
        >
          {t('action.delete')}
        </button>
        <button
          type="button"
          className="button"
          onClick={() => {
            api.downloadGpoBackup(gpo.dn, gpo.display_name ?? gpo.guid).catch(setError)
          }}
        >
          {t('gpo.backup')}
        </button>
        <button type="button" className="button" onClick={() => setCopying(true)}>
          {t('gpo.copy')}
        </button>
        <button type="button" className="button" onClick={onClose}>
          {t('action.close')}
        </button>
      </div>

      {copying && (
        <CopyGpoDialog
          gpo={gpo}
          onClose={() => setCopying(false)}
          onDone={() => {
            setCopying(false)
            onChanged(t('gpo.copied'))
          }}
        />
      )}

      {confirmDelete && (
        <DeleteGpoDialog
          gpo={gpo}
          onClose={() => setConfirmDelete(false)}
          onDone={onDeleted}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------

function GeneralTab({ gpo, onChanged }: { gpo: Gpo; onChanged: (message: string) => void }) {
  const { t } = useI18n()
  const formatDate = useDateFormat()
  const [name, setName] = useState(gpo.display_name ?? '')
  const [error, setError] = useState<unknown>(null)

  const save = useMutation({
    mutationFn: (payload: Parameters<typeof api.updateGpo>[1]) => api.updateGpo(gpo.dn, payload),
    onSuccess: () => onChanged(t('gpo.saved')),
    onError: setError,
  })

  return (
    <div className="stack-tight">
      <ErrorMessage error={error} onDismiss={() => setError(null)} />

      <label className="field">
        <span className="field__label">{t('gpo.name')}</span>
        <div className="field-inline">
          <input value={name} onChange={(event) => setName(event.target.value)} />
          <button
            type="button"
            className="button"
            disabled={!name.trim() || name === gpo.display_name || save.isPending}
            onClick={() => save.mutate({ display_name: name.trim() })}
          >
            {t('action.save')}
          </button>
        </div>
      </label>

      <dl className="facts">
        <dt>{t('gpo.guid')}</dt>
        <dd className="mono small">{gpo.guid}</dd>
        <dt>{t('gpo.path')}</dt>
        <dd className="mono small">{gpo.path}</dd>
        <dt>{t('gpo.version')}</dt>
        <dd>{t('gpo.versionPair', { machine: gpo.machine_version, user: gpo.user_version })}</dd>
        <dt>{t('gpo.created')}</dt>
        <dd>{formatDate(gpo.created)}</dd>
        <dt>{t('gpo.changed')}</dt>
        <dd>{formatDate(gpo.changed)}</dd>
      </dl>

      <fieldset className="field">
        <legend className="field__label">{t('gpo.halves')}</legend>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={gpo.machine_enabled}
            onChange={(event) => save.mutate({ machine_enabled: event.target.checked })}
          />
          <span>{t('gpo.machineEnabled')}</span>
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={gpo.user_enabled}
            onChange={(event) => save.mutate({ user_enabled: event.target.checked })}
          />
          <span>{t('gpo.userEnabled')}</span>
        </label>
        <span className="field__hint">{t('gpo.halvesHint')}</span>
      </fieldset>
    </div>
  )
}

// ---------------------------------------------------------------------------

/**
 * Where this policy is linked — and the only place it can be changed.
 *
 * A policy that is linked nowhere applies to nobody, however carefully it is
 * filled in, so this is the tab that decides whether any of the rest matters.
 * *Enforced* and *disabled* are edited in place: both are one attribute on the
 * container, and both are the kind of thing one flips while watching what a
 * client does.
 */
function LinksTab({ gpo, onChanged }: { gpo: Gpo; onChanged: (message: string) => void }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [error, setError] = useState<unknown>(null)
  const [adding, setAdding] = useState(false)

  const locations = useQuery({
    queryKey: ['gpo-locations', gpo.guid],
    queryFn: () => api.gpoLocations(gpo.guid),
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['gpo-locations', gpo.guid] })
  }

  const update = useMutation({
    mutationFn: ({ dn, changes }: { dn: string; changes: { enabled?: boolean; enforced?: boolean } }) =>
      api.updateGpoLink(dn, gpo.dn, changes),
    onSuccess: () => {
      refresh()
      onChanged(t('gpo.linkSaved'))
    },
    onError: setError,
  })

  const unlink = useMutation({
    mutationFn: (dn: string) => api.unlinkGpo(dn, gpo.dn),
    onSuccess: () => {
      refresh()
      onChanged(t('gpo.unlinked'))
    },
    onError: setError,
  })

  if (locations.isLoading) return <Spinner label={t('status.loading')} />
  if (locations.error) return <ErrorMessage error={locations.error} />

  const links = locations.data?.links ?? []

  return (
    <div className="stack-tight">
      <ErrorMessage error={error} onDismiss={() => setError(null)} />

      <div className="pane__actions">
        <button type="button" className="button" onClick={() => setAdding(true)}>
          + {t('gpo.link')}
        </button>
      </div>

      {links.length === 0 && <p className="muted">{t('gpo.notLinked')}</p>}

      {links.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t('gpo.container')}</th>
                <th className="table__cell--narrow">{t('gpo.linkOrder')}</th>
                <th className="table__cell--narrow">{t('gpo.linkState')}</th>
                <th className="table__cell--narrow" />
              </tr>
            </thead>
            <tbody>
              {links.map((link) => (
                <tr key={link.container_dn}>
                  <td>
                    <strong>{link.container}</strong>
                    <div className="muted small mono">{link.container_dn}</div>
                  </td>
                  <td>{link.order}</td>
                  <td>
                    <label className="checkbox checkbox--inline">
                      <input
                        type="checkbox"
                        checked={link.enabled}
                        disabled={update.isPending}
                        onChange={(event) =>
                          update.mutate({
                            dn: link.container_dn,
                            changes: { enabled: event.target.checked },
                          })
                        }
                      />
                      <span>{t('gpo.active')}</span>
                    </label>
                    <label className="checkbox checkbox--inline">
                      <input
                        type="checkbox"
                        checked={link.enforced}
                        disabled={update.isPending}
                        onChange={(event) =>
                          update.mutate({
                            dn: link.container_dn,
                            changes: { enforced: event.target.checked },
                          })
                        }
                      />
                      <span>{t('gpo.enforced')}</span>
                    </label>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="button button--danger"
                      disabled={unlink.isPending}
                      onClick={() => unlink.mutate(link.container_dn)}
                    >
                      {t('gpo.unlink')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {adding && (
        <LinkDialog
          gpo={gpo}
          linked={links.map((link) => link.container_dn.toLowerCase())}
          onClose={() => setAdding(false)}
          onDone={() => {
            setAdding(false)
            refresh()
            onChanged(t('gpo.linked'))
          }}
        />
      )}
    </div>
  )
}

/**
 * Pick a container to link to.
 *
 * The list is the domain root and the organisational units below it — the
 * places a policy is linked in practice. Sites are the third possibility and
 * live in their own snap-in, where the same operation belongs next to them.
 */
function LinkDialog({
  gpo,
  linked,
  onClose,
  onDone,
}: {
  gpo: Gpo
  linked: string[]
  onClose: () => void
  onDone: () => void
}) {
  const { t } = useI18n()
  const [target, setTarget] = useState('')
  const [enforced, setEnforced] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const containers = useQuery({
    queryKey: ['link-targets'],
    // The directory's own spelling, not LDAP's class name.
    queryFn: () => api.search('', { types: ['organizational_unit'] }),
  })

  const roots = useQuery({ queryKey: ['directory-roots'], queryFn: () => api.roots() })

  const link = useMutation({
    mutationFn: () => api.linkGpo(target, gpo.dn, { enforced }),
    onSuccess: onDone,
    onError: setError,
  })

  const choices = [
    ...(roots.data?.roots ?? [])
      .filter((root) => root.exists && root.kind === 'domain')
      .map((root) => ({ dn: root.dn, label: root.label })),
    ...(containers.data?.entries ?? []).map((entry) => ({
      dn: entry.dn,
      label: entry.name ?? entry.dn,
    })),
  ].filter((choice) => !linked.includes(choice.dn.toLowerCase()))

  return (
    <Modal
      title={t('gpo.link')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={!target || link.isPending}
            onClick={() => link.mutate()}
          >
            {t('gpo.link')}
          </button>
        </>
      }
    >
      <ErrorMessage error={error ?? containers.error ?? roots.error} />
      <label className="field">
        <span className="field__label">{t('gpo.container')}</span>
        <select value={target} onChange={(event) => setTarget(event.target.value)}>
          <option value="" />
          {choices.map((choice) => (
            <option key={choice.dn} value={choice.dn}>
              {choice.label} — {choice.dn}
            </option>
          ))}
        </select>
        <span className="field__hint">{t('gpo.linkHint')}</span>
      </label>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={enforced}
          onChange={(event) => setEnforced(event.target.checked)}
        />
        <span>{t('gpo.enforced')}</span>
      </label>
    </Modal>
  )
}

// ---------------------------------------------------------------------------

function FilteringTab({ gpo }: { gpo: Gpo }) {
  const { t } = useI18n()
  const filtering = useQuery({
    queryKey: ['gpo-filtering', gpo.dn],
    queryFn: () => api.gpoFiltering(gpo.dn),
  })

  if (filtering.isLoading) return <Spinner label={t('status.loading')} />
  if (filtering.error) return <ErrorMessage error={filtering.error} />

  const data = filtering.data
  if (!data) return null

  return (
    <div className="stack-tight">
      <p className="muted small">{t('gpo.filteringHint')}</p>

      <ul className="plain-list">
        {data.applies_to.map((entry) => (
          <li key={entry.trustee.sid}>
            <Badge tone="ok">{t('gpo.applies')}</Badge> {entry.trustee.name}
          </li>
        ))}
      </ul>

      {data.applies_to.length === 0 && <p className="muted">{t('gpo.appliesToNobody')}</p>}

      {data.incomplete.length > 0 && (
        <div className="alert alert--warning">
          <strong>{t('gpo.incompleteTitle')}</strong>
          <ul className="plain-list">
            {data.incomplete.map((entry) => (
              <li key={entry.trustee.sid}>
                {entry.trustee.name} —{' '}
                {entry.read ? t('gpo.readOnly') : t('gpo.applyOnly')}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------

function HealthTab({ gpo }: { gpo: Gpo }) {
  const { t } = useI18n()
  const status = useQuery({
    queryKey: ['gpo-status', gpo.dn],
    queryFn: () => api.gpoStatus(gpo.dn),
  })

  if (status.isLoading) return <Spinner label={t('status.loading')} />
  if (status.error) return <ErrorMessage error={status.error} />

  const data = status.data
  if (!data) return null

  return (
    <div className="stack-tight">
      <p className="muted small">{t('gpo.healthHint')}</p>

      <dl className="facts">
        <dt>{t('gpo.directoryVersion')}</dt>
        <dd>{data.directory_version}</dd>
        <dt>{t('gpo.sysvolVersion')}</dt>
        <dd>{data.sysvol_version ?? '—'}</dd>
      </dl>

      {/* Notes stand apart from problems on purpose: they describe states
          that are correct and merely look wrong — a half that shows as
          carrying something while the report says it holds nothing, because
          Windows keeps that extension registered. Without a word here the
          colour in the policy list is a riddle. */}
      {(data.notes ?? []).length > 0 && (
        <div className="alert alert--info">
          <ul className="plain-list">
            {(data.notes ?? []).map((note) => (
              <li key={note}>{t(`gpo.note.${note}` as MessageKey)}</li>
            ))}
          </ul>
        </div>
      )}

      {data.consistent ? (
        <div className="alert alert--success">{t('gpo.consistent')}</div>
      ) : (
        <>
          <div className="alert alert--warning">
            <ul className="plain-list">
              {data.problems.map((problem) => (
                <li key={problem}>{t(`gpo.problem.${problem}` as MessageKey)}</li>
              ))}
            </ul>
          </div>
          <Reconcile dn={gpo.dn} onDone={() => void status.refetch()} />
        </>
      )}
    </div>
  )
}

/**
 * Bring the registered extensions back in line with what the policy holds.
 *
 * Shown before applied. Registering an extension makes a policy start doing
 * what it already claims to do, and dropping one stops every client in scope
 * fetching it for nothing — but both are writes to the attribute that decides
 * whether the policy runs, and nobody should approve one sight unseen.
 *
 * The apply call recomputes rather than sending this preview back. What is on
 * screen was measured before whatever else has happened since.
 */
function Reconcile({ dn, onDone }: { dn: string; onDone: () => void }) {
  const { t } = useI18n()
  const [error, setError] = useState<unknown>(null)

  const preview = useQuery({
    queryKey: ['gpo-registration', dn],
    queryFn: () => api.gpoRegistration(dn),
    // Not on opening the tab: it walks the whole policy on the share, and the
    // status above has just done that once already.
    enabled: false,
  })

  const apply = useMutation({
    mutationFn: () => api.reconcileGpoRegistration(dn),
    onSuccess: () => {
      void preview.refetch()
      onDone()
    },
    onError: setError,
  })

  const halves = preview.data?.halves
  const entries = halves
    ? [
        ...halves.machine.missing.map((entry) => ({ half: 'machine', add: true, entry })),
        ...halves.machine.surplus.map((entry) => ({ half: 'machine', add: false, entry })),
        ...halves.user.missing.map((entry) => ({ half: 'user', add: true, entry })),
        ...halves.user.surplus.map((entry) => ({ half: 'user', add: false, entry })),
      ]
    : []

  return (
    <section className="stack-tight">
      <ErrorMessage error={error} onDismiss={() => setError(null)} />

      <div className="pane__actions">
        <button
          type="button"
          className="button"
          disabled={preview.isFetching}
          onClick={() => void preview.refetch()}
        >
          {preview.isFetching ? t('status.loading') : t('gpo.reconcileCheck')}
        </button>

        {preview.isFetched && entries.length > 0 && (
          <button
            type="button"
            className="button button--primary"
            disabled={apply.isPending}
            onClick={() => apply.mutate()}
          >
            {apply.isPending ? t('gpo.reconciling') : t('gpo.reconcileApply')}
          </button>
        )}
      </div>

      {preview.error && <ErrorMessage error={preview.error} />}

      {preview.isFetched && entries.length === 0 && !preview.error && (
        // The problems above are then ones this cannot answer — a version
        // mismatch, say, or content whose extension we do not know.
        <p className="muted small">{t('gpo.reconcileNothing')}</p>
      )}

      {entries.length > 0 && (
        <>
          <p className="muted small">{t('gpo.reconcileHint')}</p>
          <ul className="plain-list">
            {entries.map(({ half, add, entry }) => (
              <li key={`${half}:${add}:${entry.cse}`}>
                {add ? '+ ' : '− '}
                {t(half === 'machine' ? 'admx.machineHalf' : 'admx.userHalf')}
                {': '}
                <strong>
                  {/* name_for gives a short id, or the GUID when it has no
                      name for the extension. Only the first can be looked up. */}
                  {entry.name.startsWith('{')
                    ? entry.name
                    : t(`gpo.extension.${entry.name}` as MessageKey)}
                </strong>
                {!entry.name.startsWith('{') && (
                  <span className="mono small muted"> {entry.cse}</span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
