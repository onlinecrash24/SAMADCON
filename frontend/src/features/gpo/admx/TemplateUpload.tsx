/**
 * What the editor shows when the domain has no central store.
 *
 * Which is the normal state for a Samba domain: Windows brings its templates
 * along locally, so nothing ever put them on SYSVOL. Saying that plainly —
 * and offering the actions that change it — beats an empty tree. The same
 * import stays reachable from the editor's bar once the store exists.
 */

import type { AdmxStore } from '../../../api/types'
import { useI18n } from '../../../i18n'
import { BundledTemplates } from './BundledTemplates'
import { TemplateImport } from './TemplateImport'

export function TemplateUpload({
  store,
  onDone,
}: {
  store: AdmxStore | undefined
  onDone: () => void
}) {
  const { t } = useI18n()

  return (
    <div className="stack-tight">
      <p className="muted">{t('admx.noStore')}</p>
      <p className="muted small">{t('admx.noStoreHint', { path: store?.path ?? '' })}</p>

      <TemplateImport onDone={onDone} />

      <hr className="rule" />
      <BundledTemplates onDone={onDone} />
    </div>
  )
}
