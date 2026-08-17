/**
 * What a policy actually contains.
 *
 * The tab GPMC calls "Settings". Its value is not the pretty rendering but
 * completeness: anything present and unrecognised is listed as a file rather
 * than dropped, because a report that omits what it cannot read looks exactly
 * like a policy that holds nothing.
 */

import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/endpoints'
import type { Gpo, GpoHalfReport } from '../../api/types'
import { ErrorMessage, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'

export function ReportTab({ gpo }: { gpo: Gpo }) {
  const { t } = useI18n()
  const report = useQuery({
    queryKey: ['gpo-report', gpo.dn],
    queryFn: () => api.gpoReport(gpo.dn),
  })

  if (report.isLoading) return <Spinner label={t('status.loading')} />
  if (report.error) return <ErrorMessage error={report.error} />

  const data = report.data
  if (!data) return null

  return (
    <div className="stack-tight">
      <div className="field-inline">
        <span className="muted small">{t('gpo.reportHint')}</span>
        <button
          type="button"
          className="button"
          onClick={() => {
            void api.downloadGpoReport(gpo.dn, gpo.display_name ?? gpo.guid)
          }}
        >
          {t('gpo.downloadReport')}
        </button>
      </div>

      {data.empty && <p className="muted">{t('gpo.reportEmpty')}</p>}

      <HalfReport title={t('gpo.machine')} half={data.machine} />
      <HalfReport title={t('gpo.user')} half={data.user} />

      {data.unreadable.length > 0 && (
        <div className="alert alert--warning">
          <strong>{t('gpo.reportUnreadable')}</strong>
          <ul className="plain-list">
            {data.unreadable.map((item) => (
              <li key={item.path}>
                <code className="mono small">{item.path}</code> — {item.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function HalfReport({ title, half }: { title: string; half: GpoHalfReport }) {
  const { t } = useI18n()

  const hasContent =
    half.registry.length > 0 ||
    Object.keys(half.security).length > 0 ||
    Object.keys(half.scripts).length > 0 ||
    (half.redirection?.folders?.length ?? 0) > 0 ||
    half.preferences.length > 0 ||
    half.vgp.length > 0 ||
    half.other_files.length > 0

  if (!hasContent) return null

  return (
    <section className="card">
      <h3>{title}</h3>

      {half.registry.length > 0 && (
        <>
          <h4>
            {t('gpo.adminTemplates')}{' '}
            <span className="muted">({half.registry_count})</span>
          </h4>
          {half.registry.map((group) => (
            <div key={group.key} className="stack-tight">
              <code className="mono small muted">{group.key}</code>
              <div className="table-wrap">
                {/* Fixed columns: the report is a stack of small tables, and
                    letting each size itself puts every value at a different
                    place down the page. */}
                <table className="table table--pairs">
                  <tbody>
                    {group.values.map((value) => (
                      <tr key={`${group.key}/${value.value}`}>
                        <td>{value.value}</td>
                        <td className="table__cell--type muted small">{value.type}</td>
                        <td className="mono small">{value.display}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </>
      )}

      {Object.entries(half.security).map(([section, values]) => (
        <div key={section}>
          <h4>{section}</h4>
          <div className="table-wrap">
            <table className="table table--pairs">
              <tbody>
                {values.map((item) => (
                  <tr key={item.name}>
                    <td>{item.name}</td>
                    <td className="mono small">{item.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {Object.entries(half.scripts).map(([section, scripts]) => (
        <div key={section}>
          <h4>
            {t('gpo.scripts')} — {section}
          </h4>
          <ul className="plain-list">
            {scripts.map((script, index) => (
              <li key={`${section}-${index}`}>
                <code className="mono small">{script.cmdline}</code>{' '}
                <span className="muted">{script.parameters}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}

      {(half.redirection?.folders?.length ?? 0) > 0 && (
        <div>
          <h4>{t('gpo.redirection')}</h4>
          {/* The folder is shown by its GUID rather than a friendly name: the
              mapping is not on evidence yet, and a wrong label here would say
              Documents where it means Desktop. */}
          <div className="table-wrap">
            <table className="table table--compact">
              <thead>
                <tr>
                  <th>{t('gpo.redirectionFolder')}</th>
                  <th>{t('gpo.redirectionTrustee')}</th>
                  <th>{t('gpo.redirectionTarget')}</th>
                </tr>
              </thead>
              <tbody>
                {half.redirection!.folders!.flatMap((folder) =>
                  folder.targets.map((target) => (
                    <tr key={`${folder.guid}-${target.sid}`}>
                      <td className="mono small">{folder.guid}</td>
                      <td className="small">{target.sid}</td>
                      <td className="mono small">{target.path}</td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {half.preferences.map((group) => (
        <div key={`${group.type}/${group.file}`}>
          <h4>
            {t('gpo.preferences')} — {group.type}
          </h4>
          <div className="table-wrap">
            <table className="table table--pairs">
              <tbody>
                {group.items.map((item, index) => (
                  <tr key={`${group.file}-${index}`}>
                    <td>{item.attributes.name ?? item.element}</td>
                    <td className="muted small">
                      {Object.entries(item.attributes)
                        .filter(([key]) => key !== 'name')
                        .map(([key, value]) => `${key}=${value}`)
                        .join(', ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {half.vgp.map((group) => (
        <div key={group.path}>
          {/* The manifest names itself — "Symlink Policy" and the like. Better
              than the generic heading, which used to sit above the single word
              "policysetting": the reader walked the wrapper element, so every
              Samba policy looked identical and an empty one looked configured. */}
          <h4>{group.name || t('gpo.sambaPolicy')}</h4>
          <code className="mono small muted">{group.path}</code>
          {group.entries.length === 0 ? (
            <p className="muted small">{t('gpo.vgpNoEntries')}</p>
          ) : (
            <ul className="plain-list">
              {group.entries.map((entry, index) => (
                <li key={`${group.path}-${index}`}>
                  {entry.element}
                  {(entry.fields.length > 0 || entry.text) && (
                    <span className="muted small">
                      {' — '}
                      {entry.fields.length > 0
                        ? entry.fields.map((field) => `${field.name}=${field.value}`).join(', ')
                        : entry.text}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}

      {half.other_files.length > 0 && (
        <div>
          <h4>{t('gpo.otherFiles')}</h4>
          <ul className="plain-list">
            {half.other_files.map((file) => (
              <li key={file.path}>
                <code className="mono small">{file.path}</code>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
