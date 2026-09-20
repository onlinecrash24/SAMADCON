import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { api } from '../../../api/endpoints'
import type {
  ComputerDetail,
  DirectoryObject,
  GroupDetail,
  OuDetail,
  UserDetail,
} from '../../../api/types'
import { ErrorMessage, Icon, useTypeLabel } from '../../../components/primitives'
import { useI18n } from '../../../i18n'
import type { MessageKey } from '../../../i18n/messages'
import { AttributeEditor } from '../AttributeEditor'
import { ObjectCommands } from '../ObjectCommands'
import { SecurityTab } from '../SecurityTab'
import { AccountTab } from './AccountTab'
import {
  EMPTY_DRAFT,
  changesOf,
  countChanges,
  withoutApplied,
  type Changes,
  type Draft,
  type SheetBase,
  type Step,
} from './draft'
import { MembershipTab } from './MembershipTab'
import { ObjectTab } from './ObjectTab'
import { SheetProvider, type SheetApi } from './SheetContext'
import {
  AddressTab,
  ComputerGeneralTab,
  GroupGeneralTab,
  ManagedByTab,
  OrganizationTab,
  OuGeneralTab,
  ProfileTab,
  TelephonesTab,
  UserGeneralTab,
} from './tabs'

/**
 * An object's property sheet, modelled on ADUC's: the tabs it has, in the
 * order it has them, and OK / Cancel / Apply along the bottom.
 *
 * One draft for the whole window. Nothing on any tab writes to the directory;
 * OK and Apply do, in a fixed order, and Cancel discards. Apply writes in
 * steps — attributes and flags in one call, then the things that have
 * endpoints of their own — and a step that fails stops the rest: what was
 * written is dropped from the draft, what was not stays, and the error
 * names the step, so the person knows exactly which half happened.
 *
 * The tabs that keep their own state — the attribute editor and the security
 * tab — still write when their own dialogs are confirmed. ADUC's do the
 * same, and both are for people who know what they are doing.
 */

type Detail = UserDetail | GroupDetail | ComputerDetail | OuDetail | DirectoryObject

export type TabId =
  | 'general'
  | 'address'
  | 'account'
  | 'profile'
  | 'telephones'
  | 'organization'
  | 'managedBy'
  | 'members'
  | 'memberOf'
  | 'object'
  | 'security'
  | 'attributes'

function isUser(type: string): boolean {
  return type === 'user' || type === 'managed_service_account'
}

function tabsFor(type: string): TabId[] {
  if (isUser(type)) {
    return [
      'general', 'address', 'account', 'profile', 'telephones', 'organization',
      'memberOf', 'object', 'security', 'attributes',
    ]
  }
  if (type === 'group') return ['general', 'members', 'memberOf', 'managedBy', 'object', 'security', 'attributes']
  if (type === 'computer') return ['general', 'memberOf', 'managedBy', 'object', 'security', 'attributes']
  if (type === 'organizational_unit') return ['general', 'managedBy', 'object', 'security', 'attributes']
  return ['object', 'security', 'attributes']
}

/** What the directory said, in the shape the draft is compared against. */
function baseOf(object: DirectoryObject, detail: Detail, deleteProtected: boolean | undefined): SheetBase {
  const attributes = 'attributes' in detail ? detail.attributes : {}
  const base: SheetBase = { attributes, deleteProtected }
  if ('flags' in detail) base.flags = (detail as UserDetail).flags
  if ('status' in detail) {
    const user = detail as UserDetail
    base.accountExpires = user.status.account_expires
    base.mustChangePassword = user.status.must_change_password
  }
  if (object.type === 'group' && 'scope' in detail) {
    const group = detail as GroupDetail
    base.scope = group.scope
    base.securityGroup = group.security_group
  }
  if ('primary_group_dn' in detail) base.primaryGroup = (detail as UserDetail).primary_group_dn
  if ('delete_protected' in detail && (detail as OuDetail).delete_protected !== null) {
    base.deleteProtected = Boolean((detail as OuDetail).delete_protected)
  }
  return base
}

export function PropertiesSheet({
  object,
  detail,
  deleteProtected,
  onClose,
  onChanged,
  onNavigate,
  onRetarget,
}: {
  object: DirectoryObject
  detail: Detail
  /** From /security/protection, for types whose detail does not carry it. */
  deleteProtected: boolean | undefined
  onClose: () => void
  onChanged: (message: string) => void
  onNavigate: (dn: string) => void
  onRetarget: (dn: string, name: string) => void
}) {
  const { t, tn } = useI18n()
  const typeLabel = useTypeLabel()
  const queryClient = useQueryClient()

  const tabs = useMemo(() => tabsFor(object.type), [object.type])
  const [tab, setTab] = useState<TabId>(tabs[0]!)
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT)
  const [error, setError] = useState<{ step: Step; cause: unknown } | null>(null)

  const base = useMemo(() => baseOf(object, detail, deleteProtected), [object, detail, deleteProtected])
  const changes = useMemo(() => changesOf(draft, base), [draft, base])
  const pending = countChanges(changes)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['object-detail'] })
    void queryClient.invalidateQueries({ queryKey: ['object'] })
    void queryClient.invalidateQueries({ queryKey: ['children'] })
    void queryClient.invalidateQueries({ queryKey: ['members'] })
    void queryClient.invalidateQueries({ queryKey: ['memberOf'] })
    void queryClient.invalidateQueries({ queryKey: ['protection'] })
  }

  /**
   * The steps, in order. Attributes first: if the directory refuses one of
   * them nothing else has happened yet, which is the outcome easiest to
   * reason about. Membership last, because it touches other objects.
   */
  const apply = useMutation({
    mutationFn: async (what: Changes): Promise<Step[]> => {
      const applied: Step[] = []
      const run = async (step: Step, task: () => Promise<unknown>) => {
        try {
          await task()
        } catch (cause) {
          throw { step, cause, applied }
        }
        applied.push(step)
      }

      if (what.attributes || what.flags) {
        await run('attributes', () => {
          const payload = {
            ...(what.attributes ? { attributes: what.attributes } : {}),
            ...(what.flags ? { flags: what.flags } : {}),
          }
          switch (object.type) {
            case 'user':
            case 'managed_service_account':
              return api.updateUser(object.dn, payload)
            case 'group':
              return api.updateGroup(object.dn, { attributes: what.attributes })
            case 'computer':
              return api.updateComputer(object.dn, payload)
            case 'organizational_unit':
              return api.updateOu(object.dn, { attributes: what.attributes })
            default:
              return Promise.reject(new Error('This object type cannot be edited.'))
          }
        })
      }
      if (what.scope !== undefined || what.securityGroup !== undefined) {
        await run('group', () =>
          api.updateGroup(object.dn, {
            ...(what.scope !== undefined ? { scope: what.scope } : {}),
            ...(what.securityGroup !== undefined ? { security: what.securityGroup } : {}),
          }),
        )
      }
      if (what.accountExpires !== undefined) {
        await run('accountExpires', () => api.setExpiry(object.dn, what.accountExpires ?? null))
      }
      if (what.mustChangePassword !== undefined) {
        await run('mustChangePassword', () =>
          api.setMustChangePassword(object.dn, what.mustChangePassword!),
        )
      }
      if (what.unlock) {
        await run('unlock', () => api.unlock(object.dn))
      }
      if (what.deleteProtected !== undefined) {
        await run('deleteProtected', () => api.setDeleteProtection(object.dn, what.deleteProtected!))
      }
      if (what.memberRemove.length) {
        await run('memberRemove', async () => {
          for (const dn of what.memberRemove) {
            // One call, arguments swapped: the group always owns the attribute.
            if (object.type === 'group') await api.removeMembers(object.dn, [dn])
            else await api.removeMembers(dn, [object.dn])
          }
        })
      }
      if (what.memberAdd.length) {
        await run('memberAdd', async () => {
          for (const member of what.memberAdd) {
            if (object.type === 'group') await api.addMembers(object.dn, [member.dn])
            else await api.addMembers(member.dn, [object.dn])
          }
        })
      }
      // After the additions: the directory insists the account already be a
      // member, and a group added in this same draft is one by now.
      if (what.primaryGroup !== undefined) {
        await run('primaryGroup', () => api.setPrimaryGroup(object.dn, what.primaryGroup!))
      }
      return applied
    },
    onSuccess: (applied) => {
      setError(null)
      setDraft((current) => withoutApplied(current, applied))
      invalidate()
      onChanged(t('status.saved'))
    },
    onError: (failure: unknown) => {
      const { step, cause, applied } = failure as { step: Step; cause: unknown; applied: Step[] }
      setDraft((current) => withoutApplied(current, applied))
      if (applied.length) invalidate()
      setError({ step, cause })
    },
  })

  const sheetApi: SheetApi = {
    object,
    base,
    draft,
    setDraft: (update) => setDraft((current) => update(current)),
    get: (name) => (name in draft.attributes ? draft.attributes[name]! : base.attributes[name] ?? ''),
    set: (name, value) => setDraft((d) => ({ ...d, attributes: { ...d.attributes, [name]: value } })),
    flag: (name) => (name in draft.flags ? draft.flags[name]! : Boolean(base.flags?.[name])),
    setFlag: (name, value) => setDraft((d) => ({ ...d, flags: { ...d.flags, [name]: value } })),
    busy: apply.isPending,
  }

  const user = 'status' in detail ? (detail as UserDetail) : undefined
  const facts = {
    disabled: user ? user.status.disabled : null,
    lockedOut: user ? user.status.locked_out : false,
  }

  const ok = async () => {
    if (pending === 0) {
      onClose()
      return
    }
    try {
      await apply.mutateAsync(changes)
      onClose()
    } catch {
      // The error is on screen and the window stays open; that is the point.
    }
  }

  return (
    <SheetProvider value={sheetApi}>
      <header className="detail__header">
        <Icon type={object.type} className="icon--large" />
        <div>
          <h2>{object.name}</h2>
          <p className="detail__type">{typeLabel(object.type)}</p>
        </div>
      </header>

      <ObjectCommands object={object} facts={facts} onChanged={onChanged} onRetarget={onRetarget} />

      <nav className="tabs" role="tablist">
        {tabs.map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={tab === name}
            className={tab === name ? 'tabs__tab tabs__tab--active' : 'tabs__tab'}
            onClick={() => setTab(name)}
          >
            {t(`sheet.tab.${name}` as MessageKey)}
          </button>
        ))}
      </nav>

      <div className="sheet-window__panel">
        <div className="sheet-tab">
          {tab === 'general' && isUser(object.type) && <UserGeneralTab />}
          {tab === 'general' && object.type === 'group' && 'scope' in detail && (
            <GroupGeneralTab group={detail as GroupDetail} />
          )}
          {tab === 'general' && object.type === 'computer' && 'sam_account_name' in detail && (
            <ComputerGeneralTab samName={(detail as ComputerDetail).sam_account_name} />
          )}
          {tab === 'general' && object.type === 'organizational_unit' && <OuGeneralTab />}
          {tab === 'address' && <AddressTab />}
          {tab === 'account' && user && <AccountTab user={user} />}
          {tab === 'profile' && <ProfileTab />}
          {tab === 'telephones' && <TelephonesTab />}
          {tab === 'organization' && <OrganizationTab user={user} />}
          {tab === 'managedBy' && <ManagedByTab />}
          {tab === 'members' && <MembershipTab mode="members" onNavigate={onNavigate} />}
          {tab === 'memberOf' && <MembershipTab mode="memberOf" onNavigate={onNavigate} />}
          {tab === 'object' && <ObjectTab />}
          {tab === 'security' && <SecurityTab object={object} onChanged={onChanged} />}
          {tab === 'attributes' && (
            <AttributeEditor
              dn={object.dn}
              onChanged={(message) => {
                invalidate()
                onChanged(message)
              }}
            />
          )}
        </div>
      </div>

      <div className="sheet-window__footer sheet-window__footer--sheet">
        <div className="sheet-footer__status">
          {error ? (
            <div className="sheet-footer__error">
              <span className="small">
                {t('sheet.failedAt', { step: t(`sheet.step.${error.step}` as MessageKey) })}
              </span>
              <ErrorMessage error={error.cause} onDismiss={() => setError(null)} />
            </div>
          ) : (
            <span className="muted small">
              {pending === 0 ? t('detail.noChanges') : tn('sheet.pending', pending)}
            </span>
          )}
        </div>
        <div className="sheet__buttons">
          <button type="button" className="button button--primary" disabled={apply.isPending} onClick={() => void ok()}>
            {t('action.ok')}
          </button>
          <button type="button" className="button" disabled={apply.isPending} onClick={onClose}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="button"
            disabled={pending === 0 || apply.isPending}
            onClick={() => apply.mutate(changes)}
          >
            {t('action.apply')}
          </button>
        </div>
      </div>
    </SheetProvider>
  )
}
