/**
 * The model's half of the security report.
 *
 * Everything here is unverified and says so. It sits below the findings, in a
 * frame of its own, and every block it produces is labelled — a reader must be
 * able to tell an established fact from a suggestion at a glance, without
 * tracing where either came from.
 *
 * What is sent can be looked at before it goes. Domain configuration leaving
 * for another service is a decision, and a decision needs the thing itself
 * rather than a description of it — so the preview shows the exact prompt the
 * request will carry, fetched from the same function that builds it.
 *
 * The model is chosen here; the address is not. It comes from the deployment,
 * because the container makes the call and an address a user could type would
 * reach hosts their own browser cannot.
 */

import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import type { AssistantAnswer, FindingArea } from '../../api/types'
import { ErrorMessage, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n/messages'

export function AssistantReport({ area, deep }: { area: FindingArea; deep: boolean }) {
  const { t, language } = useI18n()
  const [model, setModel] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [answer, setAnswer] = useState<AssistantAnswer | null>(null)

  // An answer about the security findings must not stay on screen once the
  // reader switched to the policies. It would read as being about those.
  const [shownFor, setShownFor] = useState('')
  const key = `${area}:${deep}`
  if (answer && shownFor !== key) setAnswer(null)

  const status = useQuery({ queryKey: ['assistant'], queryFn: () => api.assistant() })

  const models = useQuery({
    queryKey: ['assistant-models'],
    queryFn: () => api.assistantModels(),
    // Not on load: it reaches out to another service, and a diagnosis page
    // should not do that because someone opened a tab.
    enabled: false,
  })

  const payload = useQuery({
    // The area and the depth belong in the key: they decide what would be
    // sent, and a preview of the wrong area is worse than none.
    queryKey: ['assistant-payload', language, area, deep],
    queryFn: () => api.assistantPayload(language, area, deep),
    enabled: false,
  })

  const report = useMutation({
    mutationFn: () => api.assistantReport(model, language, area, deep),
    onSuccess: (result) => {
      setShownFor(key)
      setAnswer(result.answer)
    },
    onError: setError,
  })

  if (status.isLoading) return null
  if (!status.data?.configured) {
    return (
      <section className="card">
        <h3>{t('assistant.title')}</h3>
        <p className="muted small">{t('assistant.notConfigured')}</p>
        <p className="muted small mono">SAMADCON_OLLAMA_URL</p>
      </section>
    )
  }

  const available = models.data?.models ?? []

  return (
    <section className="card">
      <h3>{t('assistant.title')}</h3>
      <p className="muted small">{t('assistant.intro')}</p>

      <ErrorMessage error={error} onDismiss={() => setError(null)} />

      <div className="pane__actions">
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
                {item.family ? ` (${item.family})` : ''}
              </option>
            ))}
          </select>
        )}

        <button
          type="button"
          className="button button--primary"
          disabled={!model || report.isPending}
          onClick={() => {
            setAnswer(null)
            report.mutate()
          }}
        >
          {report.isPending ? t('assistant.asking') : t('assistant.ask')}
        </button>
      </div>

      {models.isFetched && available.length === 0 && !models.error && (
        <p className="muted small">{t('assistant.noModels')}</p>
      )}
      {models.error && <ErrorMessage error={models.error} />}

      {/* Available before sending, not after. What leaves the container is a
          decision, and a decision needs the thing itself. */}
      <details onToggle={() => void (payload.isFetched || payload.refetch())}>
        <summary>{t('assistant.showPayload')}</summary>
        {payload.isFetching && <Spinner label={t('status.loading')} />}
        {payload.data && (
          // Both halves. The instructions shape the answer as much as the
          // findings do, and showing only one would be a half-truth about
          // what leaves the container.
          <pre className="payload mono small">
            {payload.data.system}
            {'\n\n'}
            {payload.data.prompt}
          </pre>
        )}
      </details>

      {answer && <Answer answer={answer} />}
    </section>
  )
}

function Answer({ answer }: { answer: AssistantAnswer }) {
  const { t } = useI18n()

  return (
    <div className="assistant">
      <p className="assistant__label">{t('assistant.unverified', { model: answer.model })}</p>

      {/* A model that ignored the schema still wrote something worth
          reading. Shown as it came, in a block that preserves its own line
          breaks — rendering its markdown would mean interpreting text the
          model chose, which is the one thing this half must not do. */}
      {!answer.structured && (
        <p className="muted small">{t('assistant.unstructured')}</p>
      )}

      {answer.summary &&
        (answer.structured ? (
          <p>{answer.summary}</p>
        ) : (
          <p className="assistant__text">{answer.summary}</p>
        ))}

      {answer.order.length > 0 && (
        <>
          <h4>{t('assistant.order')}</h4>
          <ol>
            {answer.order.map((step) => (
              // Two steps can share an id; only the subject tells them apart.
              <li key={`${step.id}:${step.subject}`}>
                <strong>{t(`findings.${step.id}` as MessageKey)}</strong>
                {step.subject && <span className="mono small"> {step.subject}</span>}
                {' — '}
                {step.reason}
              </li>
            ))}
          </ol>
        </>
      )}

      {answer.suggestions.length > 0 && (
        <>
          <h4>{t('assistant.suggestions')}</h4>
          <ul>
            {answer.suggestions.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
          <p className="muted small">{t('assistant.suggestionsHint')}</p>
        </>
      )}
    </div>
  )
}
