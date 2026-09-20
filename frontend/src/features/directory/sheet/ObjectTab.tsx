import { useQuery } from '@tanstack/react-query'

import { api } from '../../../api/endpoints'
import { Spinner, TextRow, useDateFormat, useTypeLabel } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import { useSheet } from './SheetContext'

/**
 * ADUC's Object tab: what the object is, where it is, when it was made, its
 * update sequence numbers — and the one thing on it that can be changed,
 * protection against accidental deletion.
 *
 * The canonical name is the DN read the other way round, domain first, with
 * slashes: what ADUC shows at the top of this tab.
 */
export function canonicalName(dn: string): string {
  const parts: string[] = []
  let current = ''
  for (let i = 0; i < dn.length; i++) {
    const ch = dn[i]!
    if (ch === '\\' && i + 1 < dn.length) {
      current += dn[i + 1]
      i++
    } else if (ch === ',') {
      parts.push(current)
      current = ''
    } else {
      current += ch
    }
  }
  parts.push(current)
  const dcs = parts.filter((p) => /^dc=/i.test(p)).map((p) => p.slice(3))
  const rest = parts.filter((p) => !/^dc=/i.test(p)).map((p) => p.replace(/^[A-Za-z]+=/, ''))
  return [dcs.join('.'), ...rest.reverse()].join('/')
}

export function ObjectTab() {
  const { t } = useI18n()
  const formatDate = useDateFormat()
  const typeLabel = useTypeLabel()
  const { object, base, draft, setDraft, busy } = useSheet()

  // The USNs are on no detail endpoint — they are two lines of the attribute
  // listing, read here because this is the only tab that shows them.
  const attributes = useQuery({
    queryKey: ['attributes', object.dn],
    queryFn: () => api.attributes(object.dn),
  })
  const usn = (name: string) =>
    attributes.data?.attributes[name]?.values[0]?.text ?? null

  const protection = useQuery({
    queryKey: ['protection', object.dn],
    queryFn: () => api.protection(object.dn),
    enabled: base.deleteProtected === undefined,
  })
  const protectedNow = base.deleteProtected ?? protection.data?.delete_protected ?? false
  const protectedDraft = draft.deleteProtected ?? protectedNow

  return (
    <>
      <TextRow label={t('object.canonicalName')} value={<code className="mono">{canonicalName(object.dn)}</code>} />
      <TextRow label={t('object.class')} value={typeLabel(object.type)} />
      <TextRow label={t('detail.created')} value={formatDate(object.when_created)} />
      <TextRow label={t('detail.changed')} value={formatDate(object.when_changed)} />
      {attributes.isLoading ? (
        <Spinner label={t('status.loading')} />
      ) : (
        <>
          <TextRow label={t('object.usnCurrent')} value={usn('uSNChanged')} />
          <TextRow label={t('object.usnOriginal')} value={usn('uSNCreated')} />
        </>
      )}

      <label className="checkbox">
        <input
          type="checkbox"
          checked={protectedDraft}
          disabled={busy || (base.deleteProtected === undefined && protection.isLoading)}
          onChange={(event) => setDraft((d) => ({ ...d, deleteProtected: event.target.checked }))}
        />
        <span>{t('object.protect')}</span>
      </label>
    </>
  )
}
