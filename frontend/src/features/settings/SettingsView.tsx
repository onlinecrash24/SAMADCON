/**
 * SAMADCON's own settings — kept in the domain it manages, not in the
 * container: CN=SAMADCON,CN=Program Data, one JSON document in msDS-Settings.
 * Every SAMADCON instance on the domain reads the same, and the directory's
 * backup holds them.
 *
 * For now one section: the fields a new user must have. A tester registers
 * users for Authelia, which needs a mail address on every account.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import { Badge, ErrorMessage, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'
import { fieldLabel } from '../directory/requiredUserFields'
import type { CnSource } from '../directory/userNames'

export function SettingsView() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const settings = useQuery({ queryKey: ['app-settings'], queryFn: () => api.appSettings() })
  // What the person changed; null until they touch something.
  const [draft, setDraft] = useState<{ required: string[]; cnSource: CnSource } | null>(null)

  const save = useMutation({
    mutationFn: (next: { required: string[]; cnSource: CnSource }) =>
      api.saveAppSettings({
        required_user_fields: next.required,
        cn_source: next.cnSource,
        expected: settings.data?.stamp ?? '',
      }),
    onSuccess: (next) => {
      queryClient.setQueryData(['app-settings'], next)
      setDraft(null)
    },
  })

  if (settings.isLoading) return <Spinner label={t('status.loading')} />
  if (settings.error) return <ErrorMessage error={settings.error} />
  const data = settings.data
  if (!data) return null

  const saved = {
    required: data.settings.users.required_fields,
    cnSource: data.settings.users.cn_source ?? 'name',
  }
  const current = draft ?? saved
  const changed =
    draft !== null &&
    ([...draft.required].sort().join(',') !== [...saved.required].sort().join(',') ||
      draft.cnSource !== saved.cnSource)
  const toggle = (name: string, on: boolean) =>
    setDraft({
      ...current,
      required: on ? [...current.required, name] : current.required.filter((field) => field !== name),
    })

  return (
    <div className="stack">
      <section className="card">
        <h3>{t('settings.title')}</h3>
        <p className="muted small">{t('settings.where')}</p>
        <p>
          <code className="mono small">{data.dn}</code>{' '}
          {!data.exists && <Badge tone="muted">{t('settings.notCreated')}</Badge>}
        </p>
        {!data.writable && <div className="alert alert--info">{t('settings.readOnly')}</div>}
      </section>

      <section className="card">
        <h3>{t('settings.requiredTitle')}</h3>
        <p className="muted small">{t('settings.requiredHint')}</p>
        <div className="settings__fields">
          {data.requirable_user_fields.map((name) => (
            <label className="checkbox" key={name}>
              <input
                type="checkbox"
                checked={current.required.includes(name)}
                disabled={!data.writable || save.isPending}
                onChange={(event) => toggle(name, event.target.checked)}
              />
              <span>{t(fieldLabel(name))}</span>
            </label>
          ))}
        </div>
      </section>

      <section className="card">
        <h3>{t('settings.cnTitle')}</h3>
        <p className="muted small">{t('settings.cnHint')}</p>
        {(['name', 'logon'] as const).map((source) => (
          <label className="checkbox" key={source}>
            <input
              type="radio"
              name="cn-source"
              checked={current.cnSource === source}
              disabled={!data.writable || save.isPending}
              onChange={() => setDraft({ ...current, cnSource: source })}
            />
            <span>{t(source === 'name' ? 'settings.cnFromName' : 'settings.cnFromLogon')}</span>
          </label>
        ))}
      </section>

      <section className="card">
        <ErrorMessage error={save.error} />
        <div className="pane__actions">
          <button
            type="button"
            className="button button--primary"
            disabled={!data.writable || !changed || save.isPending}
            onClick={() => save.mutate(current)}
          >
            {t('action.save')}
          </button>
          {changed && (
            <button type="button" className="button" onClick={() => setDraft(null)}>
              {t('action.discard')}
            </button>
          )}
        </div>
      </section>
    </div>
  )
}
