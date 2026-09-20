import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { api } from '../../../api/endpoints'
import type { DirectoryObject } from '../../../api/types'
import { Badge, ErrorMessage, Icon, Modal, Spinner } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import { ObjectPicker } from '../ObjectPicker'
import { withMemberAdded, withMemberRemoved } from './draft'
import { useSheet } from './SheetContext'

/**
 * Group membership from either side — Members of a group, Member Of for
 * anything that can be one — as a list with Add… and Remove that changes
 * nothing until OK or Apply.
 *
 * It used to write on every click. A tester called that "quickly
 * problematic": pick the wrong group from the search and it is already
 * done. ADUC queues the change and applies it with the sheet, and now so
 * does this. A pending addition is drawn in the list with a badge, a pending
 * removal stays in the list struck through — the list shows what the
 * directory will hold after OK, and says which parts are not there yet.
 */
export function MembershipTab({
  mode,
  onNavigate,
}: {
  mode: 'members' | 'memberOf'
  onNavigate: (dn: string) => void
}) {
  const { t } = useI18n()
  const { object, draft, setDraft, busy } = useSheet()
  const [adding, setAdding] = useState(false)

  const listing = useQuery({
    queryKey: [mode, object.dn, false],
    queryFn: () =>
      mode === 'members'
        ? api.members(object.dn, false).then((r) => r.members)
        : api.memberOf(object.dn, false).then((r) => r.groups),
  })

  const current = listing.data ?? []
  const removing = useMemo(
    () => new Set(draft.memberRemove.map((dn) => dn.toLowerCase())),
    [draft.memberRemove],
  )
  const existing = useMemo(
    () => new Set(current.map((entry) => entry.dn.toLowerCase())),
    [current],
  )
  const pickerExclude = useMemo(
    () => new Set([...existing, ...draft.memberAdd.map((o) => o.dn.toLowerCase())]),
    [existing, draft.memberAdd],
  )

  const rows: { entry: DirectoryObject; state: 'current' | 'adding' | 'removing' }[] = [
    ...current.map((entry) => ({
      entry,
      state: removing.has(entry.dn.toLowerCase()) ? ('removing' as const) : ('current' as const),
    })),
    ...draft.memberAdd.map((entry) => ({ entry, state: 'adding' as const })),
  ]

  return (
    <>
      <ErrorMessage error={listing.error} />
      {listing.isLoading && <Spinner label={t('status.loading')} />}

      {!listing.isLoading && rows.length === 0 ? (
        <p className="muted">
          {t(mode === 'members' ? 'membership.noMembers' : 'membership.noGroups')}
        </p>
      ) : (
        <table className="acl membership">
          <tbody>
            {rows.map(({ entry, state }) => {
              const primary = entry.primary_group_member || entry.primary_group
              return (
                <tr key={entry.dn} className={state === 'removing' ? 'membership__row--removing' : undefined}>
                  <td>
                    <button type="button" className="link" onClick={() => onNavigate(entry.dn)}>
                      <Icon type={entry.type} />
                      <span>{entry.name}</span>
                    </button>
                    {primary && <Badge tone="muted">{t('group.primaryMember')}</Badge>}
                    {state === 'adding' && <Badge tone="ok">{t('membership.pendingAdd')}</Badge>}
                    {state === 'removing' && <Badge tone="warn">{t('membership.pendingRemove')}</Badge>}
                    {entry.type === 'unresolved' && <Badge tone="warn">{t('type.unresolved')}</Badge>}
                  </td>
                  <td className="attrs__action">
                    {state === 'removing' ? (
                      <button
                        type="button"
                        className="link"
                        disabled={busy}
                        onClick={() => setDraft((d) => withMemberAdded(d, entry))}
                      >
                        {t('membership.keep')}
                      </button>
                    ) : (
                      !primary && (
                        <button
                          type="button"
                          className="link"
                          disabled={busy}
                          onClick={() =>
                            setDraft((d) => withMemberRemoved(d, entry.dn, state === 'current'))
                          }
                        >
                          {t('action.remove')}
                        </button>
                      )
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      <div className="detail__actions">
        <button type="button" className="button" disabled={busy} onClick={() => setAdding(true)}>
          {t(mode === 'members' ? 'membership.addMember' : 'membership.addToGroup')}
        </button>
      </div>

      {adding && (
        <Modal
          title={t(mode === 'members' ? 'membership.addMember' : 'membership.addToGroup')}
          onClose={() => setAdding(false)}
          footer={
            <button type="button" className="button" onClick={() => setAdding(false)}>
              {t('action.close')}
            </button>
          }
        >
          <div className="form">
            <ObjectPicker
              types={
                mode === 'members'
                  ? ['user', 'group', 'computer', 'contact', 'managed_service_account']
                  : ['group']
              }
              label={mode === 'members' ? 'membership.member' : 'membership.group'}
              exclude={pickerExclude}
              onSelect={(chosen) => {
                setDraft((d) => withMemberAdded(d, chosen))
                setAdding(false)
              }}
            />
          </div>
        </Modal>
      )}
    </>
  )
}
