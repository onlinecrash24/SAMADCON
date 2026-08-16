/**
 * Domain health at a glance.
 *
 * Read-only throughout. Seizing an FSMO role or forcing replication has
 * consequences a web console should not make easy to trigger by accident;
 * those belong on the DC with samba-tool.
 */

import { useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'

import { api } from '../../api/endpoints'
import type {
  DomainController,
  DomainSummary,
  FsmoRole,
  PasswordPolicy,
  ProblemAccount,
  ReplicationStatus,
} from '../../api/types'
import { Badge, ErrorMessage, Spinner, useDateFormat } from '../../components/primitives'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n/messages'

type Tab = 'overview' | 'replication' | 'policy' | 'accounts'

export function DiagnosticsView() {
  const { t } = useI18n()
  const [tab, setTab] = useState<Tab>('overview')

  const overview = useQuery({ queryKey: ['diagnostics'], queryFn: () => api.diagnostics() })

  if (overview.isLoading) return <Spinner label={t('status.loading')} />
  if (overview.error) return <ErrorMessage error={overview.error} />

  const data = overview.data
  if (!data) return null

  return (
    <>
      <div className="pane__header">
        <div className="tabs">
          {(['overview', 'replication', 'policy', 'accounts'] as Tab[]).map((id) => (
            <button
              key={id}
              type="button"
              className={tab === id ? 'tabs__tab tabs__tab--active' : 'tabs__tab'}
              onClick={() => setTab(id)}
            >
              {t(`diag.tab.${id}` as MessageKey)}
            </button>
          ))}
        </div>
      </div>

      {tab === 'overview' && (
        <div className="stack">
          <DomainCard domain={data.domain} />
          <RolesCard roles={data.roles} />
          <ControllersCard controllers={data.controllers} />
        </div>
      )}

      {tab === 'replication' && <ReplicationCard status={data.replication} />}
      {tab === 'policy' && <PolicyCard policy={data.policy} />}
      {tab === 'accounts' && <AccountsCard />}
    </>
  )
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------

function DomainCard({ domain }: { domain: DomainSummary }) {
  const { t } = useI18n()

  return (
    <section className="card">
      <h3>{domain.dns_domain}</h3>
      <dl className="facts">
        <Fact label={t('diag.netbios')} value={domain.netbios_name} />
        <Fact label={t('diag.connectedDc')} value={domain.connected_dc} />
        <Fact label={t('diag.domainLevel')} value={domain.domain_level_name} />
        <Fact label={t('diag.forestLevel')} value={domain.forest_level_name} />
        <Fact
          label={t('diag.forestRoot')}
          value={domain.is_forest_root ? t('common.yes') : t('common.no')}
        />
        <Fact label={t('diag.baseDn')} value={<code className="mono small">{domain.base_dn}</code>} />
        <Fact label={t('diag.domainSid')} value={<code className="mono small">{domain.domain_sid}</code>} />
      </dl>
    </section>
  )
}

function RolesCard({ roles }: { roles: FsmoRole[] }) {
  const { t } = useI18n()

  return (
    <section className="card">
      <h3>{t('diag.roles')}</h3>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>{t('diag.role')}</th>
              <th>{t('diag.owner')}</th>
              <th>{t('sites.site')}</th>
              <th>{t('diag.scope')}</th>
            </tr>
          </thead>
          <tbody>
            {roles.map((role) => (
              <tr key={role.role}>
                <td>{role.label}</td>
                <td>
                  {role.present ? (
                    <strong>{role.owner}</strong>
                  ) : (
                    // Missing DNS partitions are a provisioning choice, not a
                    // fault — so this is muted rather than an error.
                    <Badge tone="muted">{t('diag.notPresent')}</Badge>
                  )}
                </td>
                <td className="muted">{role.site ?? ''}</td>
                <td className="muted">{t(`diag.scope.${role.scope}` as MessageKey)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function ControllersCard({ controllers }: { controllers: DomainController[] }) {
  const { t } = useI18n()
  const formatDate = useDateFormat()

  return (
    <section className="card">
      <h3>{t('diag.controllers')}</h3>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>{t('sites.name')}</th>
              <th>{t('sites.site')}</th>
              <th>{t('diag.operatingSystem')}</th>
              <th>{t('diag.roles')}</th>
              <th>{t('diag.lastLogon')}</th>
            </tr>
          </thead>
          <tbody>
            {controllers.map((dc) => (
              <tr key={dc.dn}>
                <td>
                  <strong>{dc.name}</strong>
                  {dc.is_global_catalog && <> <Badge tone="ok">{t('sites.gc')}</Badge></>}
                  {dc.dns_name && <div className="muted small">{dc.dns_name}</div>}
                </td>
                <td>{dc.site}</td>
                <td className="muted">{dc.operating_system ?? '—'}</td>
                <td className="muted small">{dc.roles.join(', ')}</td>
                <td className="muted small">{formatDate(dc.last_logon)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Replication
// ---------------------------------------------------------------------------

function ReplicationCard({ status }: { status: ReplicationStatus }) {
  const { t } = useI18n()
  const formatDate = useDateFormat()

  return (
    <section className="card">
      <h3>{t('diag.replication')}</h3>
      <p className="muted small">{t('diag.replicationScope', { dc: status.dc })}</p>

      {status.unreadable_partitions.length > 0 && (
        <div className="alert alert--warning">
          {t('diag.unreadableReps', { partitions: status.unreadable_partitions.join(', ') })}
        </div>
      )}

      {status.neighbours.length === 0 ? (
        <p className="muted">{t('diag.noPartners')}</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t('diag.partition')}</th>
                <th>{t('diag.partner')}</th>
                <th>{t('diag.lastSuccess')}</th>
                <th>{t('diag.lastAttempt')}</th>
                <th>{t('diag.status')}</th>
              </tr>
            </thead>
            <tbody>
              {status.neighbours.map((item, index) => (
                <tr key={`${item.partition}-${item.source_guid}-${index}`}>
                  <td>{item.partition}</td>
                  <td>{item.source_dsa ?? <code className="mono small">{item.source_guid}</code>}</td>
                  <td className="small">{formatDate(item.last_success)}</td>
                  <td className="small">{formatDate(item.last_attempt)}</td>
                  <td>
                    {item.result === 0 ? (
                      <Badge tone="ok">{t('diag.ok')}</Badge>
                    ) : item.result === null ? (
                      <Badge tone="warn">{t('diag.unknown')}</Badge>
                    ) : (
                      <Badge tone="danger">
                        {t('diag.failing', { count: item.consecutive_failures })}
                      </Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Password policy
// ---------------------------------------------------------------------------

function PolicyCard({ policy }: { policy: PasswordPolicy }) {
  const { t } = useI18n()

  return (
    <div className="stack">
      <section className="card">
        <h3>{t('diag.policy')}</h3>
        <dl className="facts">
          <Fact label={t('diag.minLength')} value={policy.min_length} />
          <Fact label={t('diag.history')} value={policy.history_length} />
          <Fact
            label={t('diag.maxAge')}
            value={policy.max_age_days === null ? t('diag.never') : t('diag.days', { count: policy.max_age_days })}
          />
          <Fact
            label={t('diag.minAge')}
            value={policy.min_age_days === null ? t('diag.none') : t('diag.days', { count: policy.min_age_days })}
          />
          <Fact
            label={t('diag.complexity')}
            value={policy.complexity ? t('common.yes') : t('common.no')}
          />
          <Fact
            label={t('diag.lockoutThreshold')}
            value={
              policy.lockout_threshold ? policy.lockout_threshold : t('diag.lockoutDisabled')
            }
          />
          <Fact
            label={t('diag.lockoutDuration')}
            value={
              policy.lockout_duration_minutes === null
                ? t('diag.untilAdmin')
                : t('sites.minutes', { count: policy.lockout_duration_minutes })
            }
          />
        </dl>
        {policy.reversible_encryption && (
          <div className="alert alert--warning">{t('diag.reversibleWarning')}</div>
        )}
      </section>

      <section className="card">
        <h3>{t('diag.psos')}</h3>
        {policy.password_settings_objects.length === 0 ? (
          <p className="muted">{t('diag.noPsos')}</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('sites.name')}</th>
                  <th>{t('diag.precedence')}</th>
                  <th>{t('diag.minLength')}</th>
                  <th>{t('diag.maxAge')}</th>
                  <th>{t('diag.appliesTo')}</th>
                </tr>
              </thead>
              <tbody>
                {policy.password_settings_objects.map((pso) => (
                  <tr key={pso.dn}>
                    <td>{pso.name}</td>
                    <td>{pso.precedence}</td>
                    <td>{pso.min_length}</td>
                    <td>
                      {pso.max_age_days === null
                        ? t('diag.never')
                        : t('diag.days', { count: pso.max_age_days })}
                    </td>
                    <td className="muted small">{pso.applies_to.join(', ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted small">{t('diag.precedenceHint')}</p>
          </div>
        )}
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Accounts
// ---------------------------------------------------------------------------

function AccountsCard() {
  const { t } = useI18n()
  const accounts = useQuery({ queryKey: ['problem-accounts'], queryFn: () => api.problemAccounts() })

  if (accounts.isLoading) return <Spinner label={t('status.loading')} />
  if (accounts.error) return <ErrorMessage error={accounts.error} />

  const data = accounts.data
  if (!data) return null

  return (
    <div className="stack">
      <AccountTable title={t('diag.locked')} accounts={data.locked} kind="lockout_time" />
      <AccountTable title={t('diag.expired')} accounts={data.expired} kind="expires" />
      <AccountTable title={t('diag.disabled')} accounts={data.disabled} kind="last_logon" />
      {data.truncated && <p className="muted small">{t('list.truncated')}</p>}
    </div>
  )
}

function AccountTable({
  title,
  accounts,
  kind,
}: {
  title: string
  accounts: ProblemAccount[]
  kind: 'lockout_time' | 'expires' | 'last_logon'
}) {
  const { t } = useI18n()
  const formatDate = useDateFormat()

  return (
    <section className="card">
      <h3>
        {title} <span className="muted">({accounts.length})</span>
      </h3>
      {accounts.length === 0 ? (
        <p className="muted">{t('diag.noneOfThese')}</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t('diag.account')}</th>
                <th>{t(`diag.column.${kind}` as MessageKey)}</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((account) => (
                <tr key={account.dn}>
                  <td>
                    <strong>{account.name}</strong>
                    {account.display_name && (
                      <div className="muted small">{account.display_name}</div>
                    )}
                  </td>
                  <td className="small">{formatDate(account[kind])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------

function Fact({ label, value }: { label: string; value: ReactNode }) {
  if (value === null || value === undefined || value === '') return null
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  )
}
