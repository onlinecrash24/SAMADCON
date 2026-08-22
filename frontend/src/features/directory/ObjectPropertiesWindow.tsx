/**
 * An object's property sheet, in a window of its own.
 *
 * It fetches by DN even when whoever opened it already had the object. One
 * code path instead of two, and it is also the reload path — after a rename,
 * after a move, after somebody else changed something.
 *
 * The same [ObjectDetail] the pane beside the list shows. That is the point
 * rather than a convenience: a second description of what a property sheet
 * contains would drift, and this one is six panels deep.
 *
 * A window whose object has been deleted says so and offers to close. It does
 * not close itself — a window that vanishes is indistinguishable from a crash,
 * and the person is left guessing which happened.
 */

import { useQuery } from '@tanstack/react-query'

import { ObjectDetail } from './ObjectDetail'
import { api } from '../../api/endpoints'
import { ErrorMessage, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'

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

  if (object.isLoading) {
    return (
      <div className="sheet-window">
        <Spinner label={t('status.loading')} />
      </div>
    )
  }

  if (object.error || !object.data) {
    return (
      <div className="sheet-window">
        <ErrorMessage error={object.error} />
        {!object.error && <p className="muted">{t('window.gone')}</p>}
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
      {/* The scrolling half. Without it the sheet is cut off wherever the
          window ends, because the body around it deliberately does not
          scroll — the footer below has to stay reachable. */}
      <div className="sheet-window__panel">
        <ObjectDetail
          object={object.data}
          onChanged={onChanged}
          onNavigate={onNavigate}
          // The editable fields, the way the original opens its properties —
          // rather than the overview already visible in the pane behind.
          initialTab="edit"
          onRetarget={onRetarget}
        />
      </div>
      <div className="sheet-window__footer">
        <button type="button" className="button" onClick={onClose}>
          {t('action.close')}
        </button>
      </div>
    </div>
  )
}
