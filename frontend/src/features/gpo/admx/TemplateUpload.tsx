/**
 * What the editor shows when the domain has no central store.
 *
 * Which is the normal state for a Samba domain: Windows brings its templates
 * along locally, so nothing ever put them on SYSVOL. Saying that plainly —
 * and offering the one action that changes it — beats an empty tree.
 */

import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../../api/endpoints'
import type { AdmxStore } from '../../../api/types'
import { ErrorMessage } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import { BundledTemplates } from './BundledTemplates'

export function TemplateUpload({
  store,
  onDone,
}: {
  store: AdmxStore | undefined
  onDone: () => void
}) {
  const { t } = useI18n()
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<unknown>(null)

  const upload = useMutation({
    mutationFn: () => api.uploadTemplates(file!),
    onSuccess: onDone,
    onError: setError,
  })

  return (
    <div className="stack-tight">
      <p className="muted">{t('admx.noStore')}</p>
      <p className="muted small">
        {t('admx.noStoreHint', { path: store?.path ?? '' })}
      </p>

      <ErrorMessage error={error} onDismiss={() => setError(null)} />

      <label className="field">
        <span className="field__label">{t('admx.uploadLabel')}</span>
        <input
          type="file"
          accept=".zip,.admx,.adml"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <span className="field__hint">{t('admx.uploadHint')}</span>
      </label>

      <div>
        <button
          type="button"
          className="button button--primary"
          disabled={!file || upload.isPending}
          onClick={() => upload.mutate()}
        >
          {t('admx.upload')}
        </button>
      </div>

      <hr className="rule" />
      <BundledTemplates onDone={onDone} />
    </div>
  )
}
