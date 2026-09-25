/**
 * The central store of administrative templates, as a place of its own.
 *
 * It belongs to the domain, not to any one policy — every GPO's editor reads
 * the same store. So it has a node in the policy tree beside "All policies"
 * rather than living only inside a GPO's window, where importing templates
 * for the whole domain meant opening some unrelated policy first.
 *
 * GPMC has no such node: Windows administrators copy PolicyDefinitions onto
 * SYSVOL by hand. The page shows what that copy would otherwise leave to a
 * file browser — what is there, in which languages, and where.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../../api/endpoints'
import { ErrorMessage, Modal, Spinner } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import { BundledTemplates, useBundledMissing } from './BundledTemplates'
import { formatBytes } from './importPackage'
import { TemplateImport } from './TemplateImport'
import { TemplateUpload } from './TemplateUpload'

export function TemplateStore({ onChanged }: { onChanged: (message: string) => void }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [importing, setImporting] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const store = useQuery({ queryKey: ['admx-store'], queryFn: () => api.admxStore() })
  const bundledMissing = useBundledMissing(store.data?.templates.map((item) => item.name))

  // The server has dropped its parsed copy; everything drawn from it is stale.
  function templatesChanged() {
    void queryClient.invalidateQueries({ queryKey: ['admx-store'] })
    void queryClient.invalidateQueries({ queryKey: ['admx-tree'] })
    void queryClient.invalidateQueries({ queryKey: ['admx-search'] })
  }

  const refresh = useMutation({
    mutationFn: () => api.refreshTemplates(),
    onSuccess: (result) => {
      templatesChanged()
      onChanged(t('admx.refreshed', { policies: result.policies }))
    },
    onError: setError,
  })

  const path = store.data?.path ?? ''
  // The store's path is relative to the SYSVOL share and starts with the
  // domain's name; written out, it is the UNC path Windows administrators know.
  const realm = path.split('\\')[0] ?? ''
  const unc = realm ? `\\\\${realm}\\SYSVOL\\${path}` : path

  return (
    <>
      <div className="pane__header">
        <span className="muted small">
          {store.data?.present
            ? t('admx.storeCount', { count: store.data.templates.length })
            : t('gpo.templatesNode')}
        </span>
        <div className="pane__actions">
          {store.data?.present && (
            <button type="button" className="button" onClick={() => setImporting(true)}>
              {t('admx.import')}
            </button>
          )}
          <button
            type="button"
            className="button"
            title={t('admx.refreshHint')}
            disabled={refresh.isPending}
            onClick={() => refresh.mutate()}
          >
            {refresh.isPending ? t('status.loading') : t('admx.refresh')}
          </button>
        </div>
      </div>

      <ErrorMessage error={error ?? store.error} onDismiss={() => setError(null)} />

      {store.isLoading && <Spinner label={t('status.loading')} />}

      {store.data && !store.data.present && (
        <TemplateUpload store={store.data} onDone={templatesChanged} />
      )}

      {store.data?.present && (
        <div className="stack-tight">
          <p className="muted small">
            {t('admx.storeWhere', { path: unc })}
            <br />
            {store.data.languages.length > 0
              ? t('admx.storeLanguages', { languages: store.data.languages.join(', ') })
              : t('admx.storeNoLanguages')}
          </p>

          {bundledMissing && (
            <div className="alert alert--info">
              <BundledTemplates onDone={templatesChanged} />
            </div>
          )}

          <div className="table-wrap">
            <table className="table table--compact">
              <thead>
                <tr>
                  <th>{t('admx.storeTemplate')}</th>
                  <th>{t('admx.storeSize')}</th>
                </tr>
              </thead>
              <tbody>
                {store.data.templates.map((item) => (
                  <tr key={item.name}>
                    <td>{item.name}</td>
                    <td className="muted">{formatBytes(item.size)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {importing && (
        <Modal title={t('admx.importTitle')} onClose={() => setImporting(false)}>
          <TemplateImport onDone={templatesChanged} />
        </Modal>
      )}
    </>
  )
}
