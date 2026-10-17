/**
 * The domain and forest functional level: where it stands, what each higher
 * level still needs, and the raise.
 *
 * The raise is `samba-tool domain level raise`, with its rules checked again
 * by the server, and with what samba-tool leaves to the administrator checked
 * too: every DC at the level, the schema, functionalprep. What has to happen
 * on the DCs is shown as the command to run there; a console in a container
 * can neither edit their smb.conf nor extend the schema on the schema master.
 *
 * A raise cannot be undone. The domain's name has to be typed to confirm it.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import type { FunctionalLevelState, FunctionalLevelStep } from '../../api/types'
import { Badge, CopyButton, ErrorMessage, Field, Modal, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'
import { confirmMatches, raisePayload, scopesFor, type RaiseScope } from './functionalLevelPlan'

export function FunctionalLevelCard({ dnsDomain }: { dnsDomain: string }) {
  const { t } = useI18n()
  const levels = useQuery({ queryKey: ['functional-level'], queryFn: () => api.functionalLevel() })
  const [chosen, setChosen] = useState<number | null>(null)
  const [scope, setScope] = useState<RaiseScope>('both')
  const [confirming, setConfirming] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  if (levels.isLoading) return <Spinner label={t('status.loading')} />
  if (levels.error) return <ErrorMessage error={levels.error} />
  const data = levels.data
  if (!data) return null

  const targets = data.targets
  const target = targets.find((entry) => entry.level === chosen) ?? targets[targets.length - 1]
  const scopes = target ? scopesFor(data, target.level) : []
  const activeScope = scopes.includes(scope) ? scope : scopes[0]
  const payload = target && activeScope ? raisePayload(data, target.level, activeScope) : null
  const ready = target !== undefined && target.missing.length === 0

  return (
    <div className="stack">
      <section className="card">
        <h3>{t('fl.title')}</h3>
        {notice && <p className="muted small">{notice}</p>}
        <dl className="facts">
          <dt>{t('diag.domainLevel')}</dt>
          <dd>{data.domain_level_name}</dd>
          <dt>{t('diag.forestLevel')}</dt>
          <dd>{data.forest_level_name}</dd>
          <dt>{t('fl.schema')}</dt>
          <dd>{data.schema_version ?? '—'}</dd>
          {data.is_samba && (
            <>
              <dt>{t('fl.prep')}</dt>
              <dd>
                {t('fl.prepRevisions', {
                  forest: data.forest_revision,
                  domain: data.domain_revision,
                })}
              </dd>
            </>
          )}
        </dl>

        <div className="table-wrap">
          <table className="table table--compact">
            <thead>
              <tr>
                <th>{t('fl.controller')}</th>
                <th>{t('fl.controllerLevel')}</th>
              </tr>
            </thead>
            <tbody>
              {data.controllers.map((controller) => (
                <tr key={controller.name}>
                  <td>{controller.name}</td>
                  <td>{controller.level_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <h3>{t('fl.raiseTitle')}</h3>
        {data.is_samba ? (
          <div className="alert alert--info">{t('fl.sambaPartial')}</div>
        ) : (
          <div className="alert alert--info">{t('fl.windows')}</div>
        )}

        {target === undefined ? (
          <p className="muted">{t('fl.highest')}</p>
        ) : (
          <div className="form">
            <Field label={t('fl.target')}>
              <select
                value={target.level}
                onChange={(event) => setChosen(Number(event.target.value))}
              >
                {targets.map((entry) => (
                  <option key={entry.level} value={entry.level}>
                    {entry.name}
                  </option>
                ))}
              </select>
            </Field>

            {ready ? (
              <p>
                <Badge tone="ok">{t('fl.ready')}</Badge>
              </p>
            ) : (
              <>
                <p className="muted small">{t('fl.missingIntro', { level: target.name })}</p>
                <ol className="fl__steps">
                  {target.missing.map((step) => (
                    <Step key={step.step} step={step} samba={data.is_samba} />
                  ))}
                </ol>
                {data.is_samba && <p className="muted small">{t('fl.reload')}</p>}
              </>
            )}

            {data.is_samba && (
              <>
                <Field label={t('fl.scope')}>
                  <select
                    value={activeScope}
                    onChange={(event) => setScope(event.target.value as RaiseScope)}
                  >
                    {scopes.map((id) => (
                      <option key={id} value={id}>
                        {t(`fl.scope.${id}`)}
                      </option>
                    ))}
                  </select>
                </Field>
                <div>
                  <button
                    type="button"
                    className="button button--danger"
                    disabled={!ready || payload === null}
                    onClick={() => setConfirming(true)}
                  >
                    {t('fl.raise')}
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </section>

      {confirming && target && payload && (
        <ConfirmRaise
          levelName={target.name}
          scope={activeScope ?? 'both'}
          payload={payload}
          dnsDomain={dnsDomain}
          onClose={() => setConfirming(false)}
          onDone={(next) => {
            setChosen(null)
            setNotice(
              t('fl.done', {
                domain: next.domain_level_name ?? '',
                forest: next.forest_level_name ?? '',
              }),
            )
          }}
        />
      )}
    </div>
  )
}

function Step({ step, samba }: { step: FunctionalLevelStep; samba: boolean }) {
  const { t } = useI18n()
  if (step.step === 'dc_level') {
    const controllers = step.controllers.join(', ')
    if (!samba || !step.setting) return <li>{t('fl.step.dcWindows', { controllers })}</li>
    return (
      <li>
        {t('fl.step.dcSamba', { controllers })}
        <Command value={step.setting} />
      </li>
    )
  }
  return (
    <li>
      {t(step.step === 'schema' ? 'fl.step.schema' : 'fl.step.prep')}
      <Command value={step.command} />
    </li>
  )
}

function Command({ value }: { value: string }) {
  return (
    <div className="fl__command">
      <code className="mono small">{value}</code>
      <CopyButton value={value} />
    </div>
  )
}

function ConfirmRaise({
  levelName,
  scope,
  payload,
  dnsDomain,
  onClose,
  onDone,
}: {
  levelName: string
  scope: RaiseScope
  payload: { domain_level: number | null; forest_level: number | null }
  dnsDomain: string
  onClose: () => void
  onDone: (next: FunctionalLevelState) => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [typed, setTyped] = useState('')

  const raise = useMutation({
    mutationFn: () => api.raiseFunctionalLevel({ ...payload, confirm: typed }),
    onSuccess: (next) => {
      queryClient.setQueryData(['functional-level'], next)
      void queryClient.invalidateQueries({ queryKey: ['diagnostics'] })
      onDone(next)
      onClose()
    },
  })

  return (
    <Modal
      title={t('fl.confirmTitle', { level: levelName })}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--danger"
            disabled={raise.isPending || !confirmMatches(typed, dnsDomain)}
            onClick={() => raise.mutate()}
          >
            {t('fl.confirmButton')}
          </button>
        </>
      }
    >
      <div className="form">
        <ErrorMessage error={raise.error} />
        <p>{t(`fl.confirmScope.${scope}`, { level: levelName })}</p>
        <div className="alert alert--warning">{t('fl.confirmWarning')}</div>
        <Field label={t('fl.confirmType', { domain: dnsDomain })}>
          <input
            type="text"
            autoComplete="off"
            spellCheck={false}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
          />
        </Field>
      </div>
    </Modal>
  )
}
