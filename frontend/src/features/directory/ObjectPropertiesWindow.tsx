/**
 * An object's property sheet, in a window of its own.
 *
 * It fetches by DN even when whoever opened it already had the object. One
 * code path instead of two, and it is also the reload path — after a rename,
 * after a move, after somebody else changed something.
 *
 * Three reads before the sheet draws: the object, its typed detail, and
 * whether it is protected against deletion (which only the OU detail
 * carries, and the Object tab shows for everything). The sheet is keyed on
 * when the detail was loaded, so a reload after Apply starts it from fresh
 * values rather than a draft compared against stale ones.
 *
 * A window whose object has been deleted says so and offers to close. It does
 * not close itself — a window that vanishes is indistinguishable from a crash,
 * and the person is left guessing which happened.
 */

import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/endpoints'
import type { DirectoryObject } from '../../api/types'
import { ErrorMessage, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'
import { PropertiesSheet } from './sheet/PropertiesSheet'

function detailFor(object: DirectoryObject) {
  switch (object.type) {
    case 'user':
    case 'managed_service_account':
      return api.user(object.dn)
    case 'group':
      return api.group(object.dn)
    case 'computer':
      return api.computer(object.dn)
    case 'organizational_unit':
      return api.ou(object.dn)
    default:
      return Promise.resolve(object)
  }
}

export function ObjectPropertiesWindow({
  dn,
  onClose,
  onChanged,
  onNavigate,
  onRetarget,
}: {
  dn: string
  onClose: () => void
  onChanged: (message: string) => void
  onNavigate: (dn: string) => void
  /** The DN changed under us — a rename or a move started from this window. */
  onRetarget: (dn: string, name: string) => void
}) {
  const { t } = useI18n()

  const object = useQuery({
    queryKey: ['object', dn],
    queryFn: () => api.object(dn),
    // Not retried into a wall: the interesting failure here is "it is gone",
    // and that answer does not improve on a second attempt.
    retry: false,
  })
  const detail = useQuery({
    queryKey: ['object-detail', dn, object.data?.type],
    queryFn: () => detailFor(object.data!),
    enabled: Boolean(object.data),
  })
  const protection = useQuery({
    queryKey: ['protection', dn],
    queryFn: () => api.protection(dn),
    enabled: Boolean(object.data),
  })

  if (object.isLoading || (object.data && detail.isLoading)) {
    return (
      <div className="sheet-window">
        <Spinner label={t('status.loading')} />
      </div>
    )
  }

  if (object.error || !object.data || detail.error || !detail.data) {
    return (
      <div className="sheet-window">
        {/* A panel here too: a directory error can run to several lines, and
            without one it pushes the close button out of the window. */}
        <div className="sheet-window__panel">
          <ErrorMessage error={object.error ?? detail.error} />
          {!object.error && !detail.error && <p className="muted">{t('window.gone')}</p>}
        </div>
        <div className="sheet-window__footer">
          <button type="button" className="button" onClick={onClose}>
            {t('action.close')}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="sheet-window">
      <PropertiesSheet
        key={detail.dataUpdatedAt}
        object={object.data}
        detail={detail.data}
        deleteProtected={protection.data?.delete_protected}
        onClose={onClose}
        onChanged={onChanged}
        onNavigate={onNavigate}
        onRetarget={onRetarget}
      />
    </div>
  )
}
