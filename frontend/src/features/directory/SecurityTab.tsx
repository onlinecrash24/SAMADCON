/**
 * Permissions on a directory object.
 *
 * Two ways in, mirroring what ADUC offers: a list of the raw entries for
 * people who know what they want, and a set of delegation tasks for the
 * common cases where assembling an access mask by hand would be error-prone.
 *
 * Nothing here writes. Removing marks an entry, adding and delegating queue
 * one, and the property sheet's OK or Apply writes the lot in one go — as
 * every other tab does, and as ADUC's Security tab does. A tester found the
 * tab removing an entry the moment it was clicked, with no OK to press.
 *
 * Inherited entries are hidden by default. They usually outnumber the explicit
 * ones several times over, they cannot be edited here anyway, and burying the
 * three entries that matter under thirty that do not is how ACL editors become
 * unusable.
 */

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import type { AccessControlEntry, DirectoryObject } from '../../api/types'
import { Badge, ErrorMessage, Field, Icon, Modal, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n/messages'
import { ChosenObject, ObjectPicker } from './ObjectPicker'
import {
  withAceRemovalToggled,
  withAclAddDropped,
  withAclAdded,
  type AclAdd,
} from './sheet/draft'
import { useSheet } from './sheet/SheetContext'

/** Right combinations offered when adding an entry by hand. */
const PRESETS: Array<{ id: string; mask: number }> = [
  // Read: read properties, list contents, read permissions.
  { id: 'read', mask: 0x00000010 | 0x00000004 | 0x00020000 },
  // Read and write properties.
  { id: 'write', mask: 0x00000010 | 0x00000004 | 0x00020000 | 0x00000020 },
  // Create and delete child objects on top of that.
  { id: 'manage_children', mask: 0x00000010 | 0x00000004 | 0x00020000 | 0x00000001 | 0x00000002 },
  // Everything.
  { id: 'full_control', mask: 0x000f01ff },
]

export function SecurityTab({ object }: { object: DirectoryObject }) {
  const { t } = useI18n()
  const sheet = useSheet()

  const [showInherited, setShowInherited] = useState(false)
  const [dialog, setDialog] = useState<'add' | 'delegate' | null>(null)

  const acl = useQuery({
    queryKey: ['acl', object.dn],
    queryFn: () => api.acl(object.dn),
    // Marked entries are positions in this list. Refetching it under them
    // would move the marks; the server checks against what was read anyway.
    refetchOnWindowFocus: false,
  })

  const entries = (acl.data?.aces ?? []).filter((ace) => showInherited || !ace.inherited)
  const hiddenCount = (acl.data?.aces.length ?? 0) - entries.length
  const queued = sheet.draft.aclAdd
  const sddl = acl.data?.sddl

  const queue = (entry: AclAdd) => {
    if (sddl !== undefined) sheet.setDraft((draft) => withAclAdded(draft, entry, sddl))
    setDialog(null)
  }

  return (
    <section className="detail__section">
      <div className="detail__actions">
        <button type="button" className="button" disabled={sheet.busy || !acl.data} onClick={() => setDialog('add')}>
          {t('security.addEntry')}
        </button>
        {object.is_container && (
          <button
            type="button"
            className="button"
            disabled={sheet.busy || !acl.data}
            onClick={() => setDialog('delegate')}
          >
            {t('security.delegate')}
          </button>
        )}
      </div>

      <ErrorMessage error={acl.error} />
      {acl.isLoading && <Spinner label={t('status.loading')} />}

      {acl.data && (
        <>
          {acl.data.owner && (
            <div className="row">
              <span className="row__label">{t('security.owner')}</span>
              <span className="row__value">{acl.data.owner.name}</span>
            </div>
          )}
          {acl.data.inheritance_blocked && (
            <Badge tone="warn">{t('security.inheritanceBlocked')}</Badge>
          )}

          <label className="checkbox">
            <input
              type="checkbox"
              checked={showInherited}
              onChange={(event) => setShowInherited(event.target.checked)}
            />
            <span>
              {t('security.showInherited')}
              {hiddenCount > 0 && !showInherited && (
                <span className="muted small"> ({hiddenCount})</span>
              )}
            </span>
          </label>

          {entries.length === 0 && queued.length === 0 ? (
            <p className="muted">{t('security.noEntries')}</p>
          ) : (
            <table className="acl">
              <tbody>
                {entries.map((ace) => (
                  <AceRow
                    key={`${ace.index}-${ace.trustee.sid}`}
                    ace={ace}
                    marked={sheet.draft.aclRemove.includes(ace.index)}
                    busy={sheet.busy}
                    onToggle={() => {
                      if (sddl !== undefined) {
                        sheet.setDraft((draft) => withAceRemovalToggled(draft, ace.index, sddl))
                      }
                    }}
                  />
                ))}
                {queued.map((entry, position) => (
                  <QueuedRow
                    key={`queued-${position}`}
                    entry={entry}
                    busy={sheet.busy}
                    onDrop={() => sheet.setDraft((draft) => withAclAddDropped(draft, position))}
                  />
                ))}
              </tbody>
            </table>
          )}
          {(queued.length > 0 || sheet.draft.aclRemove.length > 0) && (
            <p className="muted small">{t('security.queuedHint')}</p>
          )}
        </>
      )}

      {dialog === 'add' && (
        <AddEntryDialog isContainer={object.is_container} onClose={() => setDialog(null)} onAdd={queue} />
      )}
      {dialog === 'delegate' && <DelegateDialog onClose={() => setDialog(null)} onAdd={queue} />}
    </section>
  )
}

function AceRow({
  ace,
  marked,
  busy,
  onToggle,
}: {
  ace: AccessControlEntry
  marked: boolean
  busy: boolean
  onToggle: () => void
}) {
  const { t } = useI18n()

  const rightsLabel = ace.full_control
    ? t('right.full_control')
    : ace.rights.map((right) => t(`right.${right}` as MessageKey)).join(', ')

  return (
    <tr className={marked ? 'acl__row--removed' : undefined}>
      <td>
        <span className="list__name">
          <Icon type={ace.trustee.kind} />
          <span>{ace.trustee.name}</span>
        </span>
        {ace.inherited && <Badge tone="muted">{t('security.inherited')}</Badge>}
        {marked && <Badge tone="danger">{t('security.markedForRemoval')}</Badge>}
      </td>
      <td>
        <Badge tone={ace.type === 'deny' ? 'danger' : 'ok'}>
          {t(ace.type === 'deny' ? 'security.deny' : 'security.allow')}
        </Badge>
      </td>
      <td className="acl__rights">
        {rightsLabel}
        {ace.object && (
          <div className="muted small">
            {t('security.limitedTo', { name: ace.object.name })}
          </div>
        )}
        {ace.applies_to && (
          <div className="muted small">
            {t('security.appliesTo', { name: ace.applies_to.name })}
          </div>
        )}
      </td>
      <td className="attrs__action">
        {!ace.inherited && (
          <button type="button" className="link" disabled={busy} onClick={onToggle}>
            {marked ? t('security.undo') : t('action.delete')}
          </button>
        )}
      </td>
    </tr>
  )
}

/** An entry queued on this tab, shown until OK or Apply writes it or it is dropped. */
function QueuedRow({ entry, busy, onDrop }: { entry: AclAdd; busy: boolean; onDrop: () => void }) {
  const { t } = useI18n()
  return (
    <tr className="acl__row--queued">
      <td>
        <span className="list__name">
          <Icon type={entry.trustee.type} />
          <span>{entry.trustee.name}</span>
        </span>
        <Badge tone="warn">{t('sheet.queued')}</Badge>
      </td>
      <td>
        {entry.kind === 'ace' ? (
          <Badge tone={entry.deny ? 'danger' : 'ok'}>
            {t(entry.deny ? 'security.deny' : 'security.allow')}
          </Badge>
        ) : (
          <Badge tone="muted">{t('security.delegate')}</Badge>
        )}
      </td>
      <td className="acl__rights">
        {entry.kind === 'ace'
          ? t(`right.${entry.preset}` as MessageKey)
          : t(`delegation.${entry.templateId}` as MessageKey)}
        {entry.kind === 'ace' && entry.inherit && (
          <div className="muted small">{t('security.inheritToChildren')}</div>
        )}
      </td>
      <td className="attrs__action">
        <button type="button" className="link" disabled={busy} onClick={onDrop}>
          {t('action.discard')}
        </button>
      </td>
    </tr>
  )
}

function AddEntryDialog({
  isContainer,
  onClose,
  onAdd,
}: {
  isContainer: boolean
  onClose: () => void
  onAdd: (entry: AclAdd) => void
}) {
  const { t } = useI18n()
  const [trustee, setTrustee] = useState<DirectoryObject | null>(null)
  const [preset, setPreset] = useState(PRESETS[0]!.id)
  const [deny, setDeny] = useState(false)
  const [inherit, setInherit] = useState(isContainer)

  const ready = Boolean(trustee?.sid)

  return (
    <Modal
      title={t('security.addEntry')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={!ready}
            onClick={() =>
              onAdd({
                kind: 'ace',
                trustee: trustee!,
                preset,
                mask: PRESETS.find((entry) => entry.id === preset)!.mask,
                deny,
                inherit: isContainer && inherit,
              })
            }
          >
            {t('action.ok')}
          </button>
        </>
      }
    >
      <div className="form">
        {trustee ? (
          <ChosenObject object={trustee} onClear={() => setTrustee(null)} />
        ) : (
          <ObjectPicker types={['user', 'group', 'computer']} onSelect={setTrustee} />
        )}

        <Field label={t('security.permission')}>
          <select value={preset} onChange={(event) => setPreset(event.target.value)}>
            {PRESETS.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {t(`right.${entry.id}` as MessageKey)}
              </option>
            ))}
          </select>
        </Field>

        <label className="checkbox">
          <input type="checkbox" checked={deny} onChange={(e) => setDeny(e.target.checked)} />
          <span>{t('security.asDeny')}</span>
        </label>
        {deny && <p className="login__insecure">{t('security.denyWarning')}</p>}

        {isContainer && (
          <label className="checkbox">
            <input type="checkbox" checked={inherit} onChange={(e) => setInherit(e.target.checked)} />
            <span>{t('security.inheritToChildren')}</span>
          </label>
        )}
      </div>
    </Modal>
  )
}

function DelegateDialog({ onClose, onAdd }: { onClose: () => void; onAdd: (entry: AclAdd) => void }) {
  const { t } = useI18n()
  const [trustee, setTrustee] = useState<DirectoryObject | null>(null)
  const [templateId, setTemplateId] = useState<string>('')

  const templates = useQuery({
    queryKey: ['delegation-templates'],
    queryFn: () => api.delegationTemplates(),
  })

  const ready = Boolean(trustee?.sid && templateId)

  return (
    <Modal
      title={t('security.delegate')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={!ready}
            onClick={() => onAdd({ kind: 'delegate', trustee: trustee!, templateId })}
          >
            {t('action.ok')}
          </button>
        </>
      }
    >
      <div className="form">
        <ErrorMessage error={templates.error} />
        {trustee ? (
          <ChosenObject object={trustee} onClear={() => setTrustee(null)} />
        ) : (
          <ObjectPicker types={['user', 'group', 'computer']} onSelect={setTrustee} />
        )}

        <Field label={t('security.task')} hint={t('security.taskHint')}>
          <select value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
            <option value="">—</option>
            {templates.data?.templates.map((template) => (
              <option key={template.id} value={template.id}>
                {t(`delegation.${template.id}` as MessageKey)}
              </option>
            ))}
          </select>
        </Field>
      </div>
    </Modal>
  )
}
