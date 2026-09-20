import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/endpoints'
import type {
  ComputerDetail,
  DirectoryObject,
  GroupDetail,
  OuDetail,
  UserDetail,
} from '../../api/types'
import { ObjectCommands } from './ObjectCommands'
import { nameFromDn } from '../../dn'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n/messages'
import {
  Badge,
  ErrorMessage,
  Icon,
  Spinner,
  TextRow,
  useDateFormat,
  useTypeLabel,
} from '../../components/primitives'

/**
 * What the pane beside the list shows about the selected object: the
 * overview, and the commands that apply to it.
 *
 * Read-only on purpose. It used to carry the editable fields and three more
 * tabs, and every one of them had its own idea of when to write. Editing
 * lives in the property window now — one draft, OK / Apply / Cancel, the
 * way ADUC's sheet works — and this pane is what ADUC's list pane is: a
 * place to look, with "Properties" one double-click away.
 */

function isUser(type: string): boolean {
  return type === 'user' || type === 'managed_service_account'
}

export interface ObjectDetailProps {
  object: DirectoryObject
  onChanged: (message: string) => void
  /** A rename or a move changed the DN out from under whoever hosts this. */
  onRetarget?: (dn: string, name: string) => void
}

export function ObjectDetail({ object, onChanged, onRetarget }: ObjectDetailProps) {
  const { t } = useI18n()
  const typeLabel = useTypeLabel()

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

  const data = detail.data
  const status = data && 'status' in data ? (data as UserDetail).status : null

  return (
    <>
      <header className="detail__header">
        <Icon type={object.type} className="icon--large" />
        <div>
          <h2>{object.name}</h2>
          <p className="detail__type">{typeLabel(object.type)}</p>
        </div>
      </header>

      <ObjectCommands
        object={object}
        facts={{
          // The loaded value when there is one, because it is fresher than the
          // row; otherwise the row's own flag, which is enough to label the
          // button and more than enough to call the endpoint.
          disabled: status ? status.disabled : null,
          // false rather than null while the detail is still loading: unknown
          // means "offer it anyway", which is right for a list row and would
          // flicker here, where the precise answer is a moment away.
          lockedOut: status ? status.locked_out : false,
        }}
        onChanged={onChanged}
        onRetarget={onRetarget}
      />

      {detail.isLoading && <Spinner label={t('status.loading')} />}
      <ErrorMessage error={detail.error} />

      {data && (
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
              as though it belonged to nothing. The window's tab resolves it. */}
        </div>
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

      {(attributes.manager || user.direct_reports.length > 0) && (
        <section className="detail__section">
          <h3>{t('detail.organization')}</h3>
          {attributes.manager && (
            <TextRow
              label={t('user.manager')}
              value={<span title={attributes.manager}>{nameFromDn(attributes.manager)}</span>}
            />
          )}
          {user.direct_reports.length > 0 && (
            <TextRow
              label={t('user.directReports')}
              value={
                <ul className="plain-list">
                  {user.direct_reports.map((dn) => (
                    <li key={dn} title={dn}>
                      {nameFromDn(dn)}
                    </li>
                  ))}
                </ul>
              }
            />
          )}
        </section>
      )}

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

