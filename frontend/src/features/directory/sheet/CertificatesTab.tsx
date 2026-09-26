import { useMutation, useQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'

import { saveBlob } from '../../../api/client'
import { api } from '../../../api/endpoints'
import type { Certificate } from '../../../api/types'
import { Badge, ErrorMessage, Modal, Spinner, TextRow, useDateFormat } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import { useSheet } from './SheetContext'

/**
 * ADUC's Published Certificates: the X.509 certificates on the account,
 * with View, Add from File, Remove and Copy to File.
 *
 * Add and Remove queue in the draft and go to the directory with OK or
 * Apply, as on every other tab. A file picked is parsed by the server first
 * — one round trip that writes nothing — so the row can show what ADUC
 * shows before anything is committed, and a file that is not a certificate
 * is refused here rather than at OK.
 *
 * "Add from Store" is not here. In ADUC it reaches into the Windows
 * certificate store on the administrator's own machine; a browser has no
 * such thing to reach into, and a button that cannot work is worse than a
 * line saying why.
 */
export function CertificatesTab() {
  const { t } = useI18n()
  const formatDate = useDateFormat()
  const { object, draft, setDraft, busy } = useSheet()
  const [viewing, setViewing] = useState<Certificate | null>(null)
  const [error, setError] = useState<unknown>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const listing = useQuery({
    queryKey: ['certificates', object.dn],
    queryFn: () => api.certificates(object.dn).then((r) => r.certificates),
  })

  const inspect = useMutation({
    mutationFn: (data: string) => api.inspectCertificate(data),
    onSuccess: (info, data) => {
      setError(null)
      const already =
        (listing.data ?? []).some((c) => c.fingerprint === info.fingerprint) ||
        draft.certAdd.some((c) => c.info.fingerprint === info.fingerprint)
      if (already) {
        setError(new Error(t('certs.alreadyThere')))
        return
      }
      setDraft((d) => ({ ...d, certAdd: [...d.certAdd, { data, info }] }))
    },
    onError: setError,
  })

  const pickFile = (file: File | undefined) => {
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      const bytes = new Uint8Array(reader.result as ArrayBuffer)
      let binary = ''
      for (const b of bytes) binary += String.fromCharCode(b)
      inspect.mutate(btoa(binary))
    }
    reader.readAsArrayBuffer(file)
  }

  // The list carries no content. One still to be added has it from the
  // inspection; one already on the account is fetched when it is wanted.
  const withContent = async (cert: Certificate): Promise<Certificate> =>
    cert.der ? cert : { ...cert, ...(await api.certificate(object.dn, cert.fingerprint)) }

  const view = async (cert: Certificate) => {
    try {
      setViewing(await withContent(cert))
    } catch (cause) {
      setError(cause)
    }
  }

  // Saved through saveBlob, which releases the URL a second later: this used
  // to revoke it straight after the click, which cancels the download in
  // Firefox.
  const download = async (cert: Certificate) => {
    try {
      const full = await withContent(cert)
      const bytes = Uint8Array.from(atob(full.der ?? ''), (c) => c.charCodeAt(0))
      saveBlob(
        new Blob([bytes], { type: 'application/pkix-cert' }),
        `${(cert.subject ?? 'certificate').replace(/[^\w.-]+/g, '_')}.cer`,
      )
    } catch (cause) {
      setError(cause)
    }
  }

  const removing = new Set(draft.certRemove)
  const rows: { cert: Certificate; state: 'current' | 'adding' | 'removing' }[] = [
    ...(listing.data ?? []).map((cert) => ({
      cert,
      state: removing.has(cert.fingerprint) ? ('removing' as const) : ('current' as const),
    })),
    ...draft.certAdd.map((entry) => ({ cert: entry.info, state: 'adding' as const })),
  ]

  return (
    <>
      <p className="muted small">{t('certs.intro')}</p>
      <ErrorMessage error={listing.error} />
      <ErrorMessage error={error} onDismiss={() => setError(null)} />
      {listing.isLoading && <Spinner label={t('status.loading')} />}

      {!listing.isLoading && rows.length === 0 ? (
        <p className="muted">{t('certs.none')}</p>
      ) : (
        <table className="table table--compact certs">
          <thead>
            <tr>
              <th>{t('certs.issuedTo')}</th>
              <th>{t('certs.issuedBy')}</th>
              <th>{t('certs.purposes')}</th>
              <th>{t('certs.expires')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map(({ cert, state }) => (
              <tr key={cert.fingerprint} className={state === 'removing' ? 'membership__row--removing' : undefined}>
                <td>
                  {cert.unparseable ? (
                    <Badge tone="warn">{t('certs.unparseable')}</Badge>
                  ) : (
                    cert.subject
                  )}
                  {state === 'adding' && <Badge tone="ok">{t('membership.pendingAdd')}</Badge>}
                  {state === 'removing' && <Badge tone="warn">{t('membership.pendingRemove')}</Badge>}
                </td>
                <td>{cert.issuer ?? ''}</td>
                <td className="muted">{cert.purposes?.length ? cert.purposes.join(', ') : '—'}</td>
                <td>{cert.not_after ? formatDate(cert.not_after) : ''}</td>
                <td className="table__actions">
                  {!cert.unparseable && (
                    <button type="button" className="link" onClick={() => void view(cert)}>
                      {t('certs.view')}
                    </button>
                  )}{' '}
                  <button type="button" className="link" onClick={() => void download(cert)}>
                    {t('certs.copyToFile')}
                  </button>{' '}
                  {state === 'adding' ? (
                    <button
                      type="button"
                      className="link link--danger"
                      disabled={busy}
                      onClick={() =>
                        setDraft((d) => ({
                          ...d,
                          certAdd: d.certAdd.filter((c) => c.info.fingerprint !== cert.fingerprint),
                        }))
                      }
                    >
                      {t('action.remove')}
                    </button>
                  ) : state === 'removing' ? (
                    <button
                      type="button"
                      className="link"
                      disabled={busy}
                      onClick={() =>
                        setDraft((d) => ({
                          ...d,
                          certRemove: d.certRemove.filter((f) => f !== cert.fingerprint),
                        }))
                      }
                    >
                      {t('membership.keep')}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="link link--danger"
                      disabled={busy}
                      onClick={() => setDraft((d) => ({ ...d, certRemove: [...d.certRemove, cert.fingerprint] }))}
                    >
                      {t('action.remove')}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="detail__actions">
        <button
          type="button"
          className="button"
          disabled={busy || inspect.isPending}
          onClick={() => fileInput.current?.click()}
        >
          {t('certs.addFromFile')}
        </button>
        <input
          ref={fileInput}
          type="file"
          accept=".cer,.crt,.pem,.der,application/x-x509-ca-cert,application/pkix-cert"
          hidden
          onChange={(event) => {
            pickFile(event.target.files?.[0])
            event.target.value = ''
          }}
        />
        <span className="muted small">{t('certs.noStore')}</span>
      </div>

      {viewing && (
        <Modal
          wide
          title={viewing.subject ?? ''}
          onClose={() => setViewing(null)}
          footer={
            <button type="button" className="button" onClick={() => setViewing(null)}>
              {t('action.close')}
            </button>
          }
        >
          <TextRow label={t('certs.issuedTo')} value={<span className="mono">{viewing.subject_dn}</span>} />
          <TextRow label={t('certs.issuedBy')} value={<span className="mono">{viewing.issuer_dn}</span>} />
          <TextRow label={t('certs.serial')} value={<span className="mono">{viewing.serial}</span>} />
          <TextRow label={t('certs.validFrom')} value={formatDate(viewing.not_before ?? null)} />
          <TextRow label={t('certs.expires')} value={formatDate(viewing.not_after ?? null)} />
          <TextRow label={t('certs.purposes')} value={viewing.purposes?.join(', ') || '—'} />
          <TextRow label={t('certs.fingerprint')} value={<span className="mono small">{viewing.fingerprint}</span>} />
          <pre className="payload mono small certs__pem">{viewing.pem}</pre>
        </Modal>
      )}
    </>
  )
}
