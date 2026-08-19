/**
 * Both reports as one document, made to be printed.
 *
 * The console answers one question at a time. A report answers the ones
 * nobody asked yet, and then it gets printed, filed and handed to someone who
 * was not there — which changes what it has to say for itself.
 *
 * It carries the values, not only the findings. "The minimum password length
 * is short" is a conclusion; a reader holding a printout cannot go and look,
 * so the policy it was drawn from is printed beside it.
 *
 * The sections reuse the diagnosis page's own cards rather than rebuilding
 * them for print. Two renderings of one truth part company on the first
 * change to either, and the one nobody looks at daily is the one that rots.
 *
 * The model's part, if asked for, is drawn inside a marked border. A border
 * repeats on every page a box breaks across, so the marking survives a report
 * long enough to need a second page — which the frame on screen never had to.
 *
 * Rendered through a portal into the body rather than where it is used. The
 * print stylesheet hides the console, and the console is this component's
 * parent: left in place, the document would have hidden itself the moment
 * anyone pressed print.
 */

import { useMutation, useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { api } from '../../api/endpoints'
import type { AssistantAnswer, Finding, FindingArea, ReportedGpo } from '../../api/types'
import { Badge, ErrorMessage, Spinner, useDateFormat } from '../../components/primitives'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n/messages'
import { Answer } from './AssistantReport'
import {
  ConnectionCard,
  ControllersCard,
  DomainCard,
  PolicyCard,
  ReplicationCard,
  RolesCard,
} from './DiagnosticsView'
import { FindingCard } from './SecurityFindings'

type Answers = Partial<Record<FindingArea, AssistantAnswer>>

const AREAS: FindingArea[] = ['security', 'policies']

export function ReportView({ deep, onClose }: { deep: boolean; onClose: () => void }) {
  const { t, language } = useI18n()
  const formatDate = useDateFormat()
  const [model, setModel] = useState('')
  const [answers, setAnswers] = useState<Answers>({})
  const [error, setError] = useState<unknown>(null)

  const report = useQuery({
    queryKey: ['domain-report', deep],
    queryFn: () => api.domainReport(deep),
  })

  const status = useQuery({ queryKey: ['assistant'], queryFn: () => api.assistant() })

  const models = useQuery({
    queryKey: ['assistant-models'],
    queryFn: () => api.assistantModels(),
    enabled: false,
  })

  const ask = useMutation({
    // One area after the other rather than both at once: a model on a small
    // host answers one request well and two badly, and there is nothing to
    // gain from reaching both halves a few seconds sooner.
    mutationFn: async (): Promise<Answers> => {
      const security = await api.assistantReport(model, language, 'security', false)
      const policies = await api.assistantReport(model, language, 'policies', deep)
      return { security: security.answer, policies: policies.answer }
    },
    onSuccess: setAnswers,
    onError: setError,
  })

  const available = models.data?.models ?? []
  const data = report.data

  return createPortal(
    <div className="report" role="dialog" aria-modal="true" aria-label={t('report.title')}>
      <div className="report__bar no-print">
        <button type="button" className="button" onClick={onClose}>
          {t('action.close')}
        </button>

        {status.data?.configured && (
          <>
            <button
              type="button"
              className="button"
              disabled={models.isFetching}
              onClick={() => void models.refetch()}
            >
              {models.isFetching ? t('status.loading') : t('assistant.loadModels')}
            </button>

            {available.length > 0 && (
              <select value={model} onChange={(event) => setModel(event.target.value)}>
                <option value="">{t('assistant.pickModel')}</option>
                {available.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}
                    {item.family ? ' (' + item.family + ')' : ''}
                  </option>
                ))}
              </select>
            )}

            <button
              type="button"
              className="button"
              disabled={!model || ask.isPending}
              onClick={() => ask.mutate()}
            >
              {ask.isPending ? t('assistant.asking') : t('report.includeModel')}
            </button>
          </>
        )}

        <button
          type="button"
          className="button button--primary"
          disabled={!data}
          onClick={() => window.print()}
        >
          {t('report.print')}
        </button>
      </div>

      <div className="report__scroll">
        {report.isLoading && <Spinner label={t('report.gathering')} />}
        {report.error && <ErrorMessage error={report.error} />}
        <ErrorMessage error={error} onDismiss={() => setError(null)} />

        {data && (
          <article className="report__page">
            <header className="report__head">
              <h1>{t('report.title')}</h1>
              <p className="report__subject">
                {data.domain.dns_domain}
                {data.domain.netbios_name ? ' (' + data.domain.netbios_name + ')' : ''}
              </p>
              <p className="muted small">
                {t('report.made', {
                  dc: data.domain.connected_dc,
                  when: formatDate(data.generated_at),
                })}
              </p>
              {/* Said at the top rather than in a footnote: a shallow report
                  cannot see settings no client applies, and a reader who does
                  not know that reads its silence as a clean result. */}
              <p className="muted small">
                {data.deep ? t('report.wasDeep') : t('report.wasShallow')}
              </p>
            </header>

            <Section title={t('report.section.connection')}>
              <ConnectionCard state={data.connection} />
            </Section>

            <Section title={t('report.section.domain')}>
              <DomainCard domain={data.domain} />
              <RolesCard roles={data.roles} />
              <ControllersCard controllers={data.controllers} />
            </Section>

            <Section title={t('report.section.password')}>
              {data.security.policy ? (
                <PolicyCard policy={data.security.policy} />
              ) : (
                <Unread names={['policy']} />
              )}
            </Section>

            <Section title={t('report.section.replication')}>
              {data.security.replication ? (
                <ReplicationCard status={data.security.replication} />
              ) : (
                <Unread names={['replication']} />
              )}
            </Section>

            <Findings
              title={t('report.section.securityFindings')}
              findings={data.security.findings}
              unreadable={data.security.unreadable}
            />

            <Section title={t('report.section.policies')}>
              <PolicyTable gpos={data.policies.gpos} deep={data.deep} />
            </Section>

            <Findings
              title={t('report.section.policyFindings')}
              findings={data.policies.findings}
              unreadable={data.policies.unreadable}
            />

            {(answers.security || answers.policies) && (
              // Framed rather than filed at the back. A reader who tears
              // off the last page should not be able to separate the
              // unverified half from its marking by accident.
              <section className="report__model">
                <h2>{t('report.section.model')}</h2>
                <p className="small">{t('report.modelWarning')}</p>

                {AREAS.map((area) => {
                  const found = answers[area]
                  return found ? (
                    <div key={area}>
                      <h3>{t(('findings.area.' + area) as MessageKey)}</h3>
                      <Answer answer={found} />
                    </div>
                  ) : null
                })}
              </section>
            )}
          </article>
        )}
      </div>
    </div>,
    document.body,
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="report__section">
      <h2>{title}</h2>
      {children}
    </section>
  )
}

function Findings({
  title,
  findings,
  unreadable,
}: {
  title: string
  findings: Finding[]
  unreadable: string[]
}) {
  const { t } = useI18n()

  return (
    <Section title={title}>
      {unreadable.length > 0 && <Unread names={unreadable} />}
      {findings.length === 0 && unreadable.length === 0 && (
        <p className="muted">{t('findings.none')}</p>
      )}
      {findings.map((finding) => (
        <FindingCard key={finding.id + ':' + finding.subject} finding={finding} />
      ))}
    </Section>
  )
}

function Unread({ names }: { names: string[] }) {
  const { t } = useI18n()
  return (
    <p className="alert alert--warning">
      {t('findings.unreadable', { sections: names.join(', ') })}
    </p>
  )
}

function PolicyTable({ gpos, deep }: { gpos: ReportedGpo[]; deep: boolean }) {
  const { t } = useI18n()

  if (gpos.length === 0) return <p className="muted">{t('report.noPolicies')}</p>

  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>{t('gpo.name')}</th>
            <th>{t('report.column.links')}</th>
            <th>{t('report.column.halves')}</th>
            <th>{t('report.column.version')}</th>
            {deep && <th>{t('report.column.sysvol')}</th>}
          </tr>
        </thead>
        <tbody>
          {gpos.map((gpo) => (
            <tr key={gpo.guid}>
              <td>
                {gpo.display_name || gpo.name}
                <br />
                <code className="mono small muted">{gpo.guid}</code>
              </td>
              <td>
                {gpo.links.length === 0 ? (
                  <span className="muted">{t('report.noLinks')}</span>
                ) : (
                  gpo.links.map((link) => (
                    <div key={link.container_dn}>
                      {link.container}
                      {!link.enabled && (
                        <>
                          {' '}
                          <Badge tone="muted">{t('report.linkDisabled')}</Badge>
                        </>
                      )}
                      {link.enforced && (
                        <>
                          {' '}
                          <Badge tone="warn">{t('report.linkEnforced')}</Badge>
                        </>
                      )}
                    </div>
                  ))
                )}
              </td>
              <td>
                <Half
                  label={t('report.machine')}
                  enabled={gpo.machine_enabled}
                  extensions={gpo.machine_extensions}
                />
                <Half
                  label={t('report.user')}
                  enabled={gpo.user_enabled}
                  extensions={gpo.user_extensions}
                />
              </td>
              <td className="mono small">
                {gpo.machine_version}/{gpo.user_version}
              </td>
              {deep && (
                <td className="mono small">
                  {gpo.status ? gpo.status.sysvol_version : <span className="muted">—</span>}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Half({
  label,
  enabled,
  extensions,
}: {
  label: string
  enabled: boolean
  extensions: string | null
}) {
  const { t } = useI18n()

  return (
    <div className="small">
      {label}:{' '}
      {!enabled ? (
        <Badge tone="muted">{t('report.halfDisabled')}</Badge>
      ) : extensions ? (
        <Badge tone="ok">{t('report.halfApplies')}</Badge>
      ) : (
        // Not a fault on its own, and not nothing either: an enabled half
        // with no extension registered is a half no client acts on.
        <Badge tone="warn">{t('report.halfEmpty')}</Badge>
      )}
    </div>
  )
}
