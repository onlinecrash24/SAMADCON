/**
 * A policy editor inside a window.
 *
 * The window holds a DN and nothing else, so this looks the policy up again
 * every time rather than being handed one. That is one code path instead of
 * two, and it is also the reload path: after a rename, after a copy, after
 * somebody else changed something.
 *
 * A policy that has since been deleted produces a message and a close button,
 * not a window that disappears. A window vanishing on its own is
 * indistinguishable from a crash, and the person is left guessing which.
 */

import { useQuery } from '@tanstack/react-query'

import { GpoDetail } from './GpoDetail'
import { api } from '../../api/endpoints'
import { ErrorMessage, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'

export function GpoWindow({
  dn,
  onClose,
  onChanged,
}: {
  dn: string
  onClose: () => void
  onChanged: (message: string) => void
}) {
  const { t } = useI18n()
  const listing = useQuery({ queryKey: ['gpos'], queryFn: () => api.gpos() })
  const gpo = listing.data?.gpos.find((entry) => entry.dn === dn)

  if (listing.isLoading) {
    return (
      <div className="sheet-window">
        <Spinner label={t('status.loading')} />
      </div>
    )
  }

  if (!gpo) {
    return (
      <div className="sheet-window">
        <ErrorMessage error={listing.error} />
        {!listing.error && <p className="muted">{t('window.gone')}</p>}
        <div className="sheet-window__footer">
          <button type="button" className="button" onClick={onClose}>
            {t('action.close')}
          </button>
        </div>
      </div>
    )
  }

  return (
    <GpoDetail
      gpo={gpo}
      onClose={onClose}
      onChanged={onChanged}
      // Deleting from inside the window is a deliberate ending, so the window
      // goes with it.
      onDeleted={() => {
        onChanged(t('gpo.deleted'))
        onClose()
      }}
    />
  )
}
