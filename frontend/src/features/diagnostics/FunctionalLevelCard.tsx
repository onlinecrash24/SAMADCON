/**
 * The domain and forest functional level: where it stands, what each higher
 * level still needs, and the command that raises it.
 *
 * Read-only. A Samba DC does not let the level be written over LDAP — not
 * even with the relax control, which it drops from an LDAP request — so the
 * raise is `samba-tool domain level raise` on the DC. What samba-tool leaves
 * to the administrator is checked here, and the command is shown only once
 * every DC runs at the level, the schema is there and functionalprep ran.
 */

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import type { FunctionalLevelStep } from '../../api/types'
import { Badge, CopyButton, ErrorMessage, Field, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'
import { chosenRaise, type RaiseScope } from './functionalLevelPlan'

export function FunctionalLevelCard() {
  const { t } = useI18n()
  const levels = useQuery({ queryKey: ['functional-level'], queryFn: () => api.functionalLevel() })
  const [chosen, setChosen] = useState<number | null>(null)
  const [scope, setScope] = useState<RaiseScope>('both')

  if (levels.isLoading) return <Spinner label={t('status.loading')} />
  if (levels.error) return <ErrorMessage error={levels.error} />
  const data = levels.data
  if (!data) return null

  const targets = data.targets
  const target = targets.find((entry) => entry.level === chosen) ?? targets[targets.length - 1]
  const ready = target !== undefined && target.missing.length === 0
  const raise = target ? chosenRaise(target, scope) : null

  return (
    <div className="stack">
      <section className="card">
        <div className="card__header">
          <h3>{t('fl.title')}</h3>
          <button type="button" className="button" onClick={() => void levels.refetch()}>
            {t('fl.reloadButton')}
          </button>
        </div>
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
              </>
            )}

            {ready && raise && (
              <>
                <Field label={t('fl.scope')}>
                  <select
                    value={raise.scope}
                    onChange={(event) => setScope(event.target.value as RaiseScope)}
                  >
                    {target.raise.map((entry) => (
                      <option key={entry.scope} value={entry.scope}>
                        {t(`fl.scope.${entry.scope}`)}
                      </option>
                    ))}
                  </select>
                </Field>
                <div className="alert alert--warning">{t('fl.raiseWarning')}</div>
                <p className="muted small">{t('fl.raiseIntro')}</p>
                <Command value={raise.command} />
              </>
            )}

            {data.is_samba && <p className="muted small">{t('fl.reload')}</p>}
          </div>
        )}
      </section>
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
