import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../api/endpoints'
import type {
  ComputerDetail,
  DirectoryObject,
  GroupDetail,
  OuDetail,
  UserDetail,
} from '../api/types'
import { AccountControls } from '../features/directory/AccountControls'
import { AttributeEditor } from '../features/directory/AttributeEditor'
import { groupsForType } from '../features/directory/fieldDefs'
import { MembershipEditor } from '../features/directory/MembershipEditor'
import { PropertySheet } from '../features/directory/PropertySheet'
import { SecurityTab } from '../features/directory/SecurityTab'
import { useI18n } from '../i18n'
import type { MessageKey } from '../i18n/messages'
import { DeleteDialog, PasswordDialog, RenameDialog } from './dialogs'
import {
  Badge,
  ErrorMessage,
  Icon,
  Spinner,
  TextRow,
  useDateFormat,
  useTypeLabel,
} from './primitives'

type Tab = 'overview' | 'edit' | 'members' | 'memberOf' | 'attributes' | 'security'

/** Object types that can belong to a group. */
const CAN_BE_MEMBER = new Set([
  'user',
  'group',
  'computer',
  'contact',
  'managed_service_account',
])

interface DetailPaneProps {
  object: DirectoryObject | null
  onChanged: (message: string) => void
  onNavigate: (dn: string) => void
}

export function DetailPane({ object, onChanged, onNavigate }: DetailPaneProps) {
  const { t } = useI18n()

  if (!object) {
    return <aside className="detail detail--empty">{t('detail.none')}</aside>
  }

  return (
    <aside className="detail">
      <ObjectDetail key={object.dn} object={object} onChanged={onChanged} onNavigate={onNavigate} />
    </aside>
  )
}

function isUser(type: string): boolean {
  return type === 'user' || type === 'managed_service_account'
}

function ObjectDetail({
  object,
  onChanged,
  onNavigate,
}: DetailPaneProps & { object: DirectoryObject }) {
  const { t } = useI18n()
  const typeLabel = useTypeLabel()
  const queryClient = useQueryClient()

  const [tab, setTab] = useState<Tab>('overview')
  const [dialog, setDialog] = useState<'password' | 'rename' | 'delete' | null>(null)
  const [actionError, setActionError] = useState<unknown>(null)
  const [saveError, setSaveError] = useState<unknown>(null)

  const detail = useQuery({
    queryKey: ['object-detail', object.dn, object.type],
    queryFn: () => {
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
    },
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['object-detail'] })
    void queryClient.invalidateQueries({ queryKey: ['children'] })
    void queryClient.invalidateQueries({ queryKey: ['tree'] })
  }

  const action = useMutation({
    mutationFn: async (task: () => Promise<string>) => task(),
    onSuccess: (message) => {
      setActionError(null)
      invalidate()
      onChanged(message)
    },
    onError: (error) => setActionError(error),
  })

  const save = useMutation({
    mutationFn: (changes: {
      attributes?: Record<string, string | null>
      flags?: Record<string, boolean>
    }) => {
      switch (object.type) {
        case 'user':
        case 'managed_service_account':
          return api.updateUser(object.dn, changes)
        case 'group':
          return api.updateGroup(object.dn, { attributes: changes.attributes })
        case 'computer':
          return api.updateComputer(object.dn, changes)
        case 'organizational_unit':
          return api.updateOu(object.dn, { attributes: changes.attributes })
        default:
          return Promise.reject(new Error('This object type cannot be edited yet.'))
      }
    },
    onSuccess: () => {
      setSaveError(null)
      invalidate()
      onChanged(t('status.saved'))
    },
    onError: (error) => setSaveError(error),
  })

  const data = detail.data
  const editable = groupsForType(object.type).length > 0
  const tabs: Tab[] = ['overview']
  if (editable) tabs.push('edit')
  if (object.type === 'group') tabs.push('members')
  if (CAN_BE_MEMBER.has(object.type)) tabs.push('memberOf')
  tabs.push('attributes', 'security')

  return (
    <>
      <header className="detail__header">
        <Icon type={object.type} className="icon--large" />
        <div>
          <h2>{object.display_name || object.name}</h2>
          <p className="detail__type">{typeLabel(object.type)}</p>
        </div>
      </header>

      <ErrorMessage error={actionError} onDismiss={() => setActionError(null)} />

      <div className="detail__actions">
        {isUser(object.type) && data && 'status' in data && (
          <>
            <button
              type="button"
              className="button"
              onClick={() =>
                action.mutate(async () => {
                  await api.setEnabled(object.dn, (data as UserDetail).status.disabled)
                  return t('status.saved')
                })
              }
            >
              {(data as UserDetail).status.disabled ? t('action.enable') : t('action.disable')}
            </button>
            {(data as UserDetail).status.locked_out && (
              <button
                type="button"
                className="button"
                onClick={() =>
                  action.mutate(async () => {
                    await api.unlock(object.dn)
                    return t('status.unlocked')
                  })
                }
              >
                {t('action.unlock')}
              </button>
            )}
            <button type="button" className="button" onClick={() => setDialog('password')}>
              {t('action.resetPassword')}
            </button>
          </>
        )}
        {object.type === 'computer' && (
          <button
            type="button"
            className="button"
            onClick={() =>
              action.mutate(async () => {
                await api.resetComputer(object.dn)
                return t('status.saved')
              })
            }
          >
            {t('action.resetAccount')}
          </button>
        )}
        <button type="button" className="button" onClick={() => setDialog('rename')}>
          {t('action.rename')}
        </button>
        <button type="button" className="button button--danger" onClick={() => setDialog('delete')}>
          {t('action.delete')}
        </button>
      </div>

      {tabs.length > 1 && (
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
              {t(`detail.tab.${name}` as MessageKey)}
            </button>
          ))}
        </nav>
      )}

      {detail.isLoading && <Spinner label={t('status.loading')} />}
      <ErrorMessage error={detail.error} />

      {data && tab === 'overview' && (
        <div className="detail__body">
          <CommonSection object={data} />
          {isUser(object.type) && 'status' in data && <UserSection user={data as UserDetail} />}
          {object.type === 'computer' && 'role' in data && (
            <ComputerSection computer={data as ComputerDetail} />
          )}
          {object.type === 'organizational_unit' && 'child_count' in data && (
            <OuSection ou={data as OuDetail} />
          )}
          {object.type === 'group' && 'scope' in data && (
            <GroupFactsSection group={data as GroupDetail} />
          )}
          {/* Group membership is deliberately not summarised here: memberOf
              omits the primary group, which would make a normal account look
              as though it belonged to nothing. The dedicated tab resolves it. */}
        </div>
      )}

      {data && tab === 'edit' && isUser(object.type) && 'status' in data && (
        <AccountControls
          user={data as UserDetail}
          onChanged={(message) => {
            invalidate()
            onChanged(message)
          }}
        />
      )}

      {data && tab === 'edit' && 'attributes' in data && (
        <PropertySheet
          // Remounts after a successful save so the drafts start from the
          // freshly loaded values instead of stale ones.
          key={detail.dataUpdatedAt}
          groups={groupsForType(object.type)}
          attributes={(data as { attributes: Record<string, string | null> }).attributes}
          flags={'flags' in data ? (data as { flags: Record<string, boolean> }).flags : undefined}
          saving={save.isPending}
          error={saveError}
          onDismissError={() => setSaveError(null)}
          onSave={(changes) => save.mutate(changes)}
        />
      )}

      {tab === 'members' && (
        <MembershipEditor
          object={object}
          mode="members"
          onChanged={(message) => {
            invalidate()
            onChanged(message)
          }}
          onNavigate={onNavigate}
        />
      )}

      {tab === 'memberOf' && (
        <MembershipEditor
          object={object}
          mode="memberOf"
          onChanged={(message) => {
            invalidate()
            onChanged(message)
          }}
          onNavigate={onNavigate}
        />
      )}

      {tab === 'attributes' && (
        <AttributeEditor
          dn={object.dn}
          onChanged={(message) => {
            invalidate()
            onChanged(message)
          }}
        />
      )}

      {tab === 'security' && <SecurityTab object={object} onChanged={onChanged} />}

      {dialog === 'password' && (
        <PasswordDialog
          dn={object.dn}
          onClose={() => setDialog(null)}
          onDone={(message) => {
            invalidate()
            onChanged(message)
          }}
        />
      )}
      {dialog === 'rename' && (
        <RenameDialog
          dn={object.dn}
          currentName={object.name}
          onClose={() => setDialog(null)}
          onDone={(message) => {
            invalidate()
            onChanged(message)
          }}
        />
      )}
      {dialog === 'delete' && (
        <DeleteDialog
          dn={object.dn}
          name={object.name}
          isContainer={object.is_container}
          isOu={object.type === 'organizational_unit'}
          onClose={() => setDialog(null)}
          onDone={(message) => {
            invalidate()
            onChanged(message)
          }}
        />
      )}
    </>
  )
}

function CommonSection({ object }: { object: DirectoryObject }) {
  const { t } = useI18n()
  const formatDate = useDateFormat()
  return (
    <section className="detail__section">
      <h3>{t('detail.general')}</h3>
      <TextRow label={t('list.description')} value={object.description} />
      <TextRow label={t('detail.created')} value={formatDate(object.when_created)} />
      <TextRow label={t('detail.changed')} value={formatDate(object.when_changed)} />
      <div className="row">
        <span className="row__label">{t('detail.dn')}</span>
        <span className="row__value mono">{object.dn}</span>
      </div>
    </section>
  )
}

function UserSection({ user }: { user: UserDetail }) {
  const { t } = useI18n()
  const formatDate = useDateFormat()
  const attributes = user.attributes

  const status = user.status.disabled
    ? { tone: 'muted' as const, key: 'user.status.disabled' as MessageKey }
    : user.status.locked_out
      ? { tone: 'danger' as const, key: 'user.status.locked' as MessageKey }
      : user.status.must_change_password
        ? { tone: 'warn' as const, key: 'user.status.mustChange' as MessageKey }
        : { tone: 'ok' as const, key: 'user.status.active' as MessageKey }

  return (
    <>
      <section className="detail__section">
        <h3>{t('detail.account')}</h3>
        <div className="row">
          <span className="row__label">Status</span>
          <span className="row__value">
            <Badge tone={status.tone}>{t(status.key)}</Badge>
          </span>
        </div>
        <TextRow label={t('user.logonName')} value={user.sam_account_name} />
        <TextRow label={t('user.upn')} value={attributes.upn} />
        <TextRow label={t('user.lastLogon')} value={formatDate(user.status.last_logon)} />
        <TextRow label={t('user.passwordLastSet')} value={formatDate(user.status.password_last_set)} />
        <TextRow label={t('user.passwordExpires')} value={formatDate(user.status.password_expires)} />
        <TextRow
          label={t('user.accountExpires')}
          value={user.status.account_expires ? formatDate(user.status.account_expires) : t('user.expiryNever')}
        />
        <TextRow label={t('user.badPasswordCount')} value={user.status.bad_password_count} />
      </section>

      <section className="detail__section">
        <h3>{t('detail.general')}</h3>
        <TextRow label={t('user.firstName')} value={attributes.first_name} />
        <TextRow label={t('user.lastName')} value={attributes.last_name} />
        <TextRow label={t('user.mail')} value={attributes.mail} />
        <TextRow label={t('user.telephone')} value={attributes.telephone} />
        <TextRow label={t('user.title')} value={attributes.title} />
        <TextRow label={t('user.department')} value={attributes.department} />
        <TextRow label={t('user.company')} value={attributes.company} />
        <TextRow label={t('user.office')} value={attributes.office} />
      </section>

      <FlagSection flags={user.flags} />
    </>
  )
}

const DANGEROUS_FLAGS = new Set([
  'password_not_required',
  'no_preauth_required',
  'trusted_for_delegation',
  'use_des_key_only',
  'encrypted_text_password_allowed',
])

/**
 * Flags that only restate what kind of object this is. The header already
 * says "User" or "Computer"; listing "normal account" underneath adds nothing
 * and pushes the options that do matter out of sight.
 */
const TYPE_FLAGS = new Set([
  'normal_account',
  'workstation_account',
  'server_account',
  'interdomain_trust_account',
])

function FlagSection({ flags }: { flags: Record<string, boolean> }) {
  const { t } = useI18n()
  const active = Object.entries(flags).filter(
    ([name, enabled]) => enabled && !TYPE_FLAGS.has(name),
  )
  if (active.length === 0) return null

  return (
    <section className="detail__section">
      <h3>{t('detail.accountOptions')}</h3>
      <ul className="flags">
        {active.map(([name]) => (
          <li key={name}>
            {t(`flag.${name}` as MessageKey)}
            {DANGEROUS_FLAGS.has(name) && <Badge tone="danger">{t('flag.dangerous')}</Badge>}
          </li>
        ))}
      </ul>
    </section>
  )
}

function GroupFactsSection({ group }: { group: GroupDetail }) {
  const { t, tn } = useI18n()
  return (
    <section className="detail__section">
      <h3>{t('detail.account')}</h3>
      <TextRow label={t('user.logonName')} value={group.sam_account_name} />
      <TextRow
        label={t('group.scope')}
        value={group.scope ? t(`group.scope.${group.scope}` as MessageKey) : null}
      />
      <TextRow
        label={t('group.type')}
        value={group.security_group ? t('group.security') : t('group.distribution')}
      />
      <TextRow label={t('detail.members')} value={tn('group.memberCount', group.member_count)} />
    </section>
  )
}

function ComputerSection({ computer }: { computer: ComputerDetail }) {
  const { t } = useI18n()
  const formatDate = useDateFormat()
  const [password, setPassword] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)

  const laps = useQuery({
    queryKey: ['laps', computer.dn],
    queryFn: () => api.lapsStatus(computer.dn),
  })

  const reveal = useMutation({
    mutationFn: () => api.revealLaps(computer.dn),
    onSuccess: (result) => {
      setError(null)
      setPassword(result.password)
    },
    onError: setError,
  })

  return (
    <section className="detail__section">
      <h3>{t('detail.account')}</h3>
      <TextRow label={t('user.logonName')} value={computer.sam_account_name} />
      <TextRow label={t('computer.dnsName')} value={computer.attributes.dns_host_name} />
      <TextRow label={t('computer.location')} value={computer.attributes.location} />
      <TextRow
        label={t('computer.os')}
        value={[computer.operating_system.name, computer.operating_system.version]
          .filter(Boolean)
          .join(' ')}
      />
      <TextRow label={t('user.lastLogon')} value={formatDate(computer.status.last_logon)} />

      <h3>{t('computer.laps')}</h3>
      {laps.data?.available ? (
        <>
          <TextRow label={t('user.passwordExpires')} value={formatDate(laps.data.expires_at ?? null)} />
          {password ? (
            <p className="mono selectable">{password}</p>
          ) : (
            <>
              <button type="button" className="button" onClick={() => reveal.mutate()}>
                {t('computer.lapsReveal')}
              </button>
              <p className="muted small">{t('computer.lapsWarning')}</p>
            </>
          )}
          <ErrorMessage error={error} onDismiss={() => setError(null)} />
        </>
      ) : (
        <p className="muted">{t('computer.lapsUnavailable')}</p>
      )}
    </section>
  )
}

function OuSection({ ou }: { ou: OuDetail }) {
  const { t, tn } = useI18n()
  return (
    <section className="detail__section">
      <h3>{t('detail.general')}</h3>
      <TextRow label={t('detail.contents')} value={tn('ou.childCount', ou.child_count)} />
      {ou.delete_protected && <Badge tone="ok">{t('ou.protected')}</Badge>}
      {ou.block_inheritance && <Badge tone="warn">{t('ou.blockInheritance')}</Badge>}
    </section>
  )
}

