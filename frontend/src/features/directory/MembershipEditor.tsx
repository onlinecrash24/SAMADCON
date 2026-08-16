/**
 * Group membership, from either side.
 *
 * ``members`` lists what is inside a group; ``memberOf`` lists the groups an
 * object belongs to. Both edit the same attribute — ``member`` on the group —
 * which is why adding a user to a group and adding a group to a user are the
 * same call with the arguments swapped.
 *
 * Primary group membership is the exception: it lives in the member's
 * ``primaryGroupID`` and cannot be removed here, only replaced by making
 * another group primary. It is marked rather than silently omitted, because a
 * user whose only visible group is "Domain Users" looks broken otherwise.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { api } from '../../api/endpoints'
import type { DirectoryObject } from '../../api/types'
import { Badge, ErrorMessage, Icon, Modal, Spinner } from '../../components/primitives'
import { useI18n } from '../../i18n'
import { ObjectPicker } from './ObjectPicker'

type Mode = 'members' | 'memberOf'

interface MembershipEditorProps {
  /** The object whose membership is shown. */
  object: DirectoryObject
  mode: Mode
  onChanged: (message: string) => void
  onNavigate: (dn: string) => void
}

export function MembershipEditor({ object, mode, onChanged, onNavigate }: MembershipEditorProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const [recursive, setRecursive] = useState(false)
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const listing = useQuery({
    queryKey: [mode, object.dn, recursive],
    queryFn: () =>
      mode === 'members'
        ? api.members(object.dn, recursive).then((result) => result.members)
        : api.memberOf(object.dn, recursive).then((result) => result.groups),
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['members'] })
    void queryClient.invalidateQueries({ queryKey: ['memberOf'] })
    void queryClient.invalidateQueries({ queryKey: ['object-detail'] })
  }

  const add = useMutation({
    mutationFn: (chosen: DirectoryObject) =>
      // One call, arguments swapped: the group always owns the attribute.
      mode === 'members'
        ? api.addMembers(object.dn, [chosen.dn])
        : api.addMembers(chosen.dn, [object.dn]),
    onSuccess: () => {
      setError(null)
      setAdding(false)
      refresh()
      onChanged(t('membership.added'))
    },
    onError: setError,
  })

  const remove = useMutation({
    mutationFn: (entry: DirectoryObject) =>
      mode === 'members'
        ? api.removeMembers(object.dn, [entry.dn])
        : api.removeMembers(entry.dn, [object.dn]),
    onSuccess: () => {
      setError(null)
      refresh()
      onChanged(t('membership.removed'))
    },
    onError: setError,
  })

  const entries = listing.data ?? []
  const existing = useMemo(
    () => new Set(entries.map((entry) => entry.dn.toLowerCase())),
    [entries],
  )

  return (
    <section className="detail__section">
      <div className="detail__actions">
        <button type="button" className="button" onClick={() => setAdding(true)}>
          {t(mode === 'members' ? 'membership.addMember' : 'membership.addToGroup')}
        </button>
      </div>

      <label className="checkbox">
        <input
          type="checkbox"
          checked={recursive}
          onChange={(event) => setRecursive(event.target.checked)}
        />
        <span>{t('detail.recursive')}</span>
      </label>

      <ErrorMessage error={error} onDismiss={() => setError(null)} />
      <ErrorMessage error={listing.error} />
      {listing.isLoading && <Spinner label={t('status.loading')} />}

      {entries.length === 0 && !listing.isLoading ? (
        <p className="muted">
          {t(mode === 'members' ? 'membership.noMembers' : 'membership.noGroups')}
        </p>
      ) : (
        <table className="acl">
          <tbody>
            {entries.map((entry) => {
              // Primary membership is not stored in `member`, so removing it
              // here would fail — the directory wants another group made
              // primary instead.
              const primary = entry.primary_group_member || entry.primary_group
              return (
                <tr key={entry.dn}>
                  <td>
                    <button type="button" className="link" onClick={() => onNavigate(entry.dn)}>
                      <Icon type={entry.type} />
                      <span>{entry.display_name || entry.name}</span>
                    </button>
                    {primary && <Badge tone="muted">{t('group.primaryMember')}</Badge>}
                    {entry.type === 'unresolved' && (
                      <Badge tone="warn">{t('type.unresolved')}</Badge>
                    )}
                  </td>
                  <td className="attrs__action">
                    {!primary && !recursive && (
                      <button
                        type="button"
                        className="link"
                        disabled={remove.isPending}
                        onClick={() => remove.mutate(entry)}
                      >
                        {t('action.remove')}
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      {recursive && entries.length > 0 && (
        <p className="muted small">{t('membership.recursiveHint')}</p>
      )}

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
            <ErrorMessage error={add.error} />
            <ObjectPicker
              // Adding to a group means picking a group; adding a member means
              // picking anything that can be one.
              types={
                mode === 'members'
                  ? ['user', 'group', 'computer', 'contact', 'managed_service_account']
                  : ['group']
              }
              label={mode === 'members' ? 'membership.member' : 'membership.group'}
              exclude={existing}
              onSelect={(chosen) => add.mutate(chosen)}
            />
          </div>
        </Modal>
      )}
    </section>
  )
}
