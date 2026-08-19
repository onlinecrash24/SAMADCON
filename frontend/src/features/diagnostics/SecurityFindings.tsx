/**
 * The KI-Manager: two reports, each with a binding half and an unverified one.
 *
 * Every line above the model's frame was decided by a rule in
 * `core/findings.py` over values the tool reads itself, and carries the values
 * it was decided from. The evidence is shown rather than hidden behind a
 * disclosure: a finding that says "the minimum password length is 6, measured
 * against 8" can be argued with; one that says "the password policy is weak"
 * can only be believed.
 *
 * The two areas answer different questions, so they are tabs rather than one
 * long list. Only the policies offer the deep pass — it is a walk of every
 * policy's files, which is what finds settings no client will ever read, and
 * one round trip per policy is not something to spend on every page load.
 */

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import type { Finding, FindingArea } from '../../api/types'
import { Badge, ErrorMessage, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n/messages'
import { AssistantReport } from './AssistantReport'

const AREAS: FindingArea[] = ['security', 'policies']

const TONE = {
  high: 'danger',
  medium: 'warn',
  low: 'muted',
  info: 'muted',
} as const

export function SecurityFindings() {
  const { t } = useI18n()
  const [area, setArea] = useState<FindingArea>('security')
  const [deep, setDeep] = useState(false)

  const report = useQuery({
    // Both belong in the key: each changes what the server sends back, not
    // just how it is drawn.
    queryKey: ['findings', area, deep],
    queryFn: () => api.securityFindings(area, deep),
  })

  return (
    <>
      <div className="pane__header">
        <div className="tabs">
          {AREAS.map((id) => (
            <button
              key={id}
              type="button"
              className={area === id ? 'tabs__tab tabs__tab--active' : 'tabs__tab'}
              onClick={() => setArea(id)}
            >
              {t(`findings.area.${id}` as MessageKey)}
            </button>
          ))}
        </div>

        {area === 'policies' && (
          <label className="checkbox checkbox--inline" title={t('findings.deepHint')}>
            <input type="checkbox" checked={deep} onChange={(e) => setDeep(e.target.checked)} />
            <span>{t('findings.deep')}</span>
          </label>
        )}
      </div>

      <div className="stack">
        <p className="muted small">{t(`findings.intro.${area}` as MessageKey)}</p>

        {report.isLoading && <Spinner label={t('status.loading')} />}
        {report.error && <ErrorMessage error={report.error} />}

        {report.data && (
          <>
            {report.data.unreadable.length > 0 && (
              // Said outright: a section nobody could read has no findings,
              // and that is not the same as having none.
              <div className="alert alert--warning">
                {t('findings.unreadable', { sections: report.data.unreadable.join(', ') })}
              </div>
            )}

            {report.data.findings.length === 0 && report.data.unreadable.length === 0 && (
              <div className="alert alert--success">{t('findings.none')}</div>
            )}

            {report.data.findings.map((finding) => (
              // Keyed by both: several policies share an id, and the id alone
              // would collapse them into one row.
              <FindingCard key={`${finding.id}:${finding.subject}`} finding={finding} />
            ))}

            {/* Below the findings, never among them. */}
            <AssistantReport area={area} deep={deep} />
          </>
        )}
      </div>
    </>
  )
}

function FindingCard({ finding }: { finding: Finding }) {
  const { t } = useI18n()
  const evidence = Object.entries(finding.evidence)

  return (
    <section className="card">
      <div className="badge-row">
        <Badge tone={TONE[finding.severity] ?? 'muted'}>
          {t(`findings.severity.${finding.severity}` as MessageKey)}
        </Badge>
        {/* Which policy, before what is wrong with it: a reader scanning a
            list of twenty is looking for the name first. */}
        {finding.subject && <span className="mono small">{finding.subject}</span>}
      </div>

      <h3>{t(`findings.${finding.id}` as MessageKey)}</h3>
      <p>{t(`findings.${finding.id}.why` as MessageKey)}</p>

      {evidence.length > 0 && (
        <p className="muted small mono">
          {evidence.map(([key, value]) => `${key}=${String(value)}`).join('  ')}
        </p>
      )}
    </section>
  )
}
