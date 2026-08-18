/**
 * The security report's binding half.
 *
 * Every line here was decided by a rule in `core/findings.py` over values the
 * tool reads itself, and carries the values it was decided from. Nothing on
 * this screen comes from a language model; when the Ollama adapter is
 * configured its output appears elsewhere and says so, because a reader has to
 * be able to tell an established fact from a suggestion without checking where
 * it came from.
 *
 * The evidence is shown rather than hidden behind a disclosure. A finding that
 * says "the minimum password length is 6, measured against 8" can be argued
 * with; one that says "the password policy is weak" can only be believed.
 */

import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/endpoints'
import type { Finding } from '../../api/types'
import { Badge, ErrorMessage, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'
import { AssistantReport } from './AssistantReport'
import type { MessageKey } from '../../i18n/messages'

const TONE = {
  high: 'danger',
  medium: 'warn',
  low: 'muted',
  info: 'muted',
} as const

export function SecurityFindings() {
  const { t } = useI18n()

  const report = useQuery({
    queryKey: ['security-findings'],
    queryFn: () => api.securityFindings(),
  })

  if (report.isLoading) return <Spinner label={t('status.loading')} />
  if (report.error) return <ErrorMessage error={report.error} />

  const data = report.data
  if (!data) return null

  return (
    <div className="stack">
      <p className="muted small">{t('findings.intro')}</p>

      {data.unreadable.length > 0 && (
        // Said outright: a section nobody could read has no findings, and that
        // is not the same as having none.
        <div className="alert alert--warning">
          {t('findings.unreadable', { sections: data.unreadable.join(', ') })}
        </div>
      )}

      {data.findings.length === 0 && data.unreadable.length === 0 && (
        <div className="alert alert--success">{t('findings.none')}</div>
      )}

      {data.findings.map((finding) => (
        <FindingCard key={finding.id} finding={finding} />
      ))}

      {/* Below the findings, never among them. */}
      <AssistantReport />
    </div>
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
