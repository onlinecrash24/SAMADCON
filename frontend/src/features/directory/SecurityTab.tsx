/**
 * Permissions on a directory object.
 *
 * Two ways in, mirroring what ADUC offers: a list of the raw entries for
 * people who know what they want, and a set of delegation tasks for the
 * common cases where assembling an access mask by hand would be error-prone.
 *
 * Inherited entries are hidden by default. They usually outnumber the explicit
 * ones several times over, they cannot be edited here anyway, and burying the
 * three entries that matter under thirty that do not is how ACL editors become
 * unusable.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import type { AccessControlEntry, DirectoryObject } from '../../api/types'
import { Badge, ErrorMessage, Field, Icon, Modal, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n/messages'
import { ChosenObject, ObjectPicker } from './ObjectPicker'

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

interface SecurityTabProps {
  object: DirectoryObject
  onChanged: (message: string) => void
}

export function SecurityTab({ object, onChanged }: SecurityTabProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const [showInherited, setShowInherited] = useState(false)
  const [dialog, setDialog] = useState<'add' | 'delegate' | null>(null)
  const [error, setError] = useState<unknown>(null)

  const acl = useQuery({
    queryKey: ['acl', object.dn],
    queryFn: () => api.acl(object.dn),
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['acl', object.dn] })
  }

  const remove = useMutation({
    mutationFn: (entry: AccessControlEntry) =>
      api.removeAce(object.dn, entry.index, acl.data?.sddl),
    onSuccess: () => {
      setError(null)
      refresh()
      onChanged(t('security.entryRemoved'))
    },
    onError: setError,
  })

  const entries = (acl.data?.aces ?? []).filter((ace) => showInherited || !ace.inherited)
  const hiddenCount = (acl.data?.aces.length ?? 0) - entries.length

  return (
    <section className="detail__section">
      <div className="detail__actions">
        <button type="button" className="button" onClick={() => setDialog('add')}>
          {t('security.addEntry')}
        </button>
        {object.is_container && (
          <button type="button" className="button" onClick={() => setDialog('delegate')}>
            {t('security.delegate')}
          </button>
        )}
      </div>

      <ErrorMessage error={error} onDismiss={() => setError(null)} />
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

          {entries.length === 0 ? (
            <p className="muted">{t('security.noEntries')}</p>
          ) : (
            <table className="acl">
              <tbody>
                {entries.map((ace) => (
                  <AceRow
                    key={`${ace.index}-${ace.trustee.sid}`}
                    ace={ace}
                    onRemove={() => remove.mutate(ace)}
                  />
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      {dialog === 'add' && acl.data && (
        <AddEntryDialog
          dn={object.dn}
          expectedSddl={acl.data.sddl}
          isContainer={object.is_container}
          onClose={() => setDialog(null)}
          onDone={() => {
            refresh()
            setDialog(null)
            onChanged(t('security.entryAdded'))
          }}
        />
      )}

      {dialog === 'delegate' && acl.data && (
        <DelegateDialog
          dn={object.dn}
          expectedSddl={acl.data.sddl}
          onClose={() => setDialog(null)}
          onDone={() => {
            refresh()
            setDialog(null)
            onChanged(t('security.delegated'))
          }}
        />
      )}
    </section>
  )
}

function AceRow({ ace, onRemove }: { ace: AccessControlEntry; onRemove: () => void }) {
  const { t } = useI18n()

  const rightsLabel = ace.full_control
    ? t('right.full_control')
    : ace.rights.map((right) => t(`right.${right}` as MessageKey)).join(', ')

  return (
    <tr>
      <td>
        <span className="list__name">
          <Icon type={ace.trustee.kind} />
          <span>{ace.trustee.name}</span>
        </span>
        {ace.inherited && <Badge tone="muted">{t('security.inherited')}</Badge>}
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
          <button type="button" className="link" onClick={onRemove}>
            {t('action.delete')}
          </button>
        )}
      </td>
    </tr>
  )
}

function AddEntryDialog({
  dn,
  expectedSddl,
  isContainer,
  onClose,
  onDone,
}: {
  dn: string
  expectedSddl: string
  isContainer: boolean
  onClose: () => void
  onDone: () => void
}) {
  const { t } = useI18n()
  const [trustee, setTrustee] = useState<DirectoryObject | null>(null)
  const [preset, setPreset] = useState(PRESETS[0]!.id)
  const [deny, setDeny] = useState(false)
  const [inherit, setInherit] = useState(isContainer)

  const add = useMutation({
    mutationFn: () =>
      api.addAce(dn, {
        trustee_sid: trustee!.sid!,
        mask: PRESETS.find((entry) => entry.id === preset)!.mask,
        deny,
        inherit_to_children: inherit,
        expected_sddl: expectedSddl,
      }),
    onSuccess: onDone,
  })

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
            disabled={!ready || add.isPending}
            onClick={() => add.mutate()}
          >
            {t('action.save')}
          </button>
        </>
      }
    >
      <div className="form">
        <ErrorMessage error={add.error} />
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

function DelegateDialog({
  dn,
  expectedSddl,
  onClose,
  onDone,
}: {
  dn: string
  expectedSddl: string
  onClose: () => void
  onDone: () => void
}) {
  const { t } = useI18n()
  const [trustee, setTrustee] = useState<DirectoryObject | null>(null)
  const [templateId, setTemplateId] = useState<string>('')

  const templates = useQuery({
    queryKey: ['delegation-templates'],
    queryFn: () => api.delegationTemplates(),
  })

  const delegate = useMutation({
    mutationFn: () => api.delegate(dn, templateId, trustee!.sid!, expectedSddl),
    onSuccess: onDone,
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
            disabled={!ready || delegate.isPending}
            onClick={() => delegate.mutate()}
          >
            {t('action.save')}
          </button>
        </>
      }
    >
      <div className="form">
        <ErrorMessage error={delegate.error} />
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
