/**
 * Importing administrative templates into the central store.
 *
 * Three routes, because administrators have the templates in three shapes:
 * Microsoft's MSI as it was downloaded, a ZIP of the PolicyDefinitions folder,
 * or that folder itself. The server reshapes all three the same way; what the
 * browser decides is only what to send.
 *
 * Reachable at any time, not just while the domain has no store: a second
 * import — a newer Windows release, another language — was impossible when
 * this form only showed up for an empty store.
 */

import { useMutation } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../../../api/endpoints'
import type { AdmxImportResult, ExistingTemplates } from '../../../api/types'
import { Banner, ErrorMessage } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import {
  DEFAULT_LANGUAGES,
  MAX_UPLOAD_BYTES,
  MICROSOFT_LANGUAGES,
  folderFilesToSend,
  formatBytes,
} from './importPackage'

type Source = { kind: 'files'; files: File[] } | { kind: 'folder'; files: File[] }

export function TemplateImport({ onDone }: { onDone: (result: AdmxImportResult) => void }) {
  const { t } = useI18n()
  const [source, setSource] = useState<Source | null>(null)
  const [languages, setLanguages] = useState<string[]>(DEFAULT_LANGUAGES)
  const [existing, setExisting] = useState<ExistingTemplates>('skip')
  const [result, setResult] = useState<AdmxImportResult | null>(null)
  const [error, setError] = useState<unknown>(null)

  // React has no prop for it, and TypeScript no attribute: set it by hand.
  const folderInput = useRef<HTMLInputElement>(null)
  useEffect(() => {
    folderInput.current?.setAttribute('webkitdirectory', '')
  }, [])

  // What would go over the wire. A folder is narrowed down here; a file is
  // sent whole and narrowed down on the server, which can open it.
  const outgoing = useMemo(() => {
    if (!source) return null
    if (source.kind === 'files') {
      const files = source.files.map((file) => ({ file, name: file.name, size: file.size }))
      return { files, left: 0, bytes: files.reduce((total, item) => total + item.size, 0) }
    }
    const picked = source.files.map((file) => ({
      file,
      name: file.webkitRelativePath || file.name,
      path: file.webkitRelativePath || file.name,
      size: file.size,
    }))
    const { send, left, bytes } = folderFilesToSend(picked, languages)
    return { files: send, left, bytes }
  }, [source, languages])

  const tooLarge = Boolean(outgoing && outgoing.bytes > MAX_UPLOAD_BYTES)

  const run = useMutation({
    mutationFn: () =>
      api.importTemplates(
        outgoing!.files.map(({ file, name }) => ({ file, name })),
        { existing, languages },
      ),
    onSuccess: (done) => {
      setResult(done)
      setError(null)
      onDone(done)
    },
    onError: (cause) => {
      setResult(null)
      setError(cause)
    },
  })

  function toggle(language: string, on: boolean) {
    setLanguages((current) =>
      on ? [...current, language] : current.filter((item) => item !== language),
    )
  }

  const others = MICROSOFT_LANGUAGES.filter((item) => !DEFAULT_LANGUAGES.includes(item))
  const blocked =
    !outgoing || outgoing.files.length === 0 || languages.length === 0 || tooLarge || run.isPending

  return (
    <div className="stack-tight">
      <ErrorMessage error={error} onDismiss={() => setError(null)} />

      <label className="field">
        <span className="field__label">{t('admx.importFiles')}</span>
        <input
          type="file"
          multiple
          accept=".msi,.zip,.admx,.adml"
          onChange={(event) => {
            const files = Array.from(event.target.files ?? [])
            setSource(files.length ? { kind: 'files', files } : null)
            setResult(null)
            if (folderInput.current) folderInput.current.value = ''
          }}
        />
        <span className="field__hint">{t('admx.importFilesHint')}</span>
      </label>

      <label className="field">
        <span className="field__label">{t('admx.importFolder')}</span>
        <input
          ref={folderInput}
          type="file"
          multiple
          onChange={(event) => {
            const files = Array.from(event.target.files ?? [])
            setSource(files.length ? { kind: 'folder', files } : null)
            setResult(null)
          }}
        />
        <span className="field__hint">{t('admx.importFolderHint')}</span>
      </label>

      {outgoing && (
        <p className="muted small">
          {source?.kind === 'folder'
            ? t('admx.importPickedFolder', {
                count: outgoing.files.length,
                size: formatBytes(outgoing.bytes),
                left: outgoing.left,
              })
            : t('admx.importPicked', {
                count: outgoing.files.length,
                size: formatBytes(outgoing.bytes),
              })}
        </p>
      )}
      {tooLarge && (
        <Banner
          tone="warning"
          message={t('admx.importTooLarge', { size: formatBytes(outgoing!.bytes) })}
        />
      )}

      <fieldset className="radio-group radio-group--block">
        <legend>{t('admx.importLanguages')}</legend>
        {DEFAULT_LANGUAGES.map((language) => (
          <label className="checkbox" key={language}>
            <input
              type="checkbox"
              checked={languages.includes(language)}
              onChange={(event) => toggle(language, event.target.checked)}
            />
            <span>{language}</span>
          </label>
        ))}
        <details>
          <summary className="small">{t('admx.importMoreLanguages')}</summary>
          <div className="admx-import__languages">
            {others.map((language) => (
              <label className="checkbox checkbox--inline" key={language}>
                <input
                  type="checkbox"
                  checked={languages.includes(language)}
                  onChange={(event) => toggle(language, event.target.checked)}
                />
                <span>{language}</span>
              </label>
            ))}
          </div>
        </details>
        <p className="field__hint">
          {languages.length === 0 ? t('admx.importNoLanguage') : t('admx.importLanguagesHint')}
        </p>
      </fieldset>

      <fieldset className="radio-group radio-group--block">
        <legend>{t('admx.importExisting')}</legend>
        {(['skip', 'replace'] as ExistingTemplates[]).map((mode) => (
          <label className="checkbox" key={mode}>
            <input
              type="radio"
              name="admx-existing"
              checked={existing === mode}
              onChange={() => setExisting(mode)}
            />
            <span>{mode === 'skip' ? t('admx.importSkip') : t('admx.importReplace')}</span>
          </label>
        ))}
      </fieldset>

      <div>
        <button
          type="button"
          className="button button--primary"
          disabled={blocked}
          onClick={() => run.mutate()}
        >
          {run.isPending ? t('status.loading') : t('admx.importRun')}
        </button>
      </div>

      {result && (
        <div className="alert alert--info">
          <div className="alert__body">
            <p>
              {t('admx.importDone', {
                added: result.added.length,
                replaced: result.replaced.length,
                skipped: result.skipped.length,
              })}{' '}
              {result.imported_languages.length > 0 &&
                t('admx.importDoneLanguages', { languages: result.imported_languages.join(', ') })}
            </p>
            {result.missing_languages.length > 0 && (
              <p>{t('admx.importMissing', { languages: result.missing_languages.join(', ') })}</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
