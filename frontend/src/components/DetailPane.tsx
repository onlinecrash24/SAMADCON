/**
 * The object shown beside the list.
 *
 * A preview, and only that: single click fills it, and the same sheet opens as
 * a window when someone wants to keep it — or wants two. Both are
 * [ObjectDetail], so what a property sheet *is* is written down once.
 *
 * Keyed by DN here and not in the window, because this is the thing that swaps
 * objects underneath itself. A window never does.
 */

import { ObjectDetail } from '../features/directory/ObjectDetail'
import type { DirectoryObject } from '../api/types'
import { useI18n } from '../i18n'

export function DetailPane({
  object,
  onChanged,
  onNavigate,
  onRetarget,
}: {
  object: DirectoryObject | null
  onChanged: (message: string) => void
  onNavigate: (dn: string) => void
  /** A rename or a move from in here changed the DN. */
  onRetarget?: (dn: string, name: string) => void
}) {
  const { t } = useI18n()

  if (!object) {
    return <aside className="detail detail--empty">{t('detail.none')}</aside>
  }

  return (
    <aside className="detail">
      <ObjectDetail
        key={object.dn}
        object={object}
        onChanged={onChanged}
        onNavigate={onNavigate}
        onRetarget={onRetarget}
      />
    </aside>
  )
}
