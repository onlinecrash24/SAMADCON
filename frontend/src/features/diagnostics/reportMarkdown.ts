/**
 * The domain report as Markdown, and the name of the file it goes into.
 *
 * Asked for by a tester who wants to hand a report to a language model. The
 * console itself still asks nothing of one: this writes a file, and what
 * happens to it is up to whoever downloads it.
 *
 * It follows ReportView section by section and says what the cards say. A
 * second rendering of one truth is what that file warns against, and this is
 * one all the same — a card is JSX and a file is text. The test pins the
 * sections and their order, so a section added on screen and forgotten here
 * does not go unnoticed for long.
 *
 * Two things differ from the screen on purpose. Times are printed as they
 * came, in UTC with their offset, not in the reader's locale: a file is read
 * somewhere else, often by a program. And nothing is styled: a badge becomes
 * its word.
 *
 * Every value from the directory goes through cell(). A policy's name is
 * whatever someone typed, and unescaped it could close a table, open a
 * heading or pose as a link. That protects the document's shape. It does not
 * make the text harmless to a model that reads it, which is why the export
 * says where its contents come from.
 */

import type {
  AccountExposure,
  ConnectionState,
  DomainController,
  DomainReport,
  DomainSummary,
  Finding,
  FsmoRole,
  PasswordPolicy,
  ReplicationStatus,
  ReportedGpo,
} from '../../api/types'
import type { MessageKey } from '../../i18n/messages'

type Params = Record<string, string | number>

/** The two functions of useI18n this needs; a test passes its own. */
export interface Words {
  t: (key: MessageKey, params?: Params) => string
  tn: (key: never, count: number, params?: Params) => string
}

/** One value as table-cell or inline text that cannot change the structure. */
export function cell(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
    .replace(/\r?\n|\r/g, ' ')
    .replace(/\\/g, '\\\\')
    .replace(/([|`*_<[#])/g, '\\$1')
    .trim()
}

/** A value shown as code: backticks cannot be escaped inside a code span. */
function code(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  const text = String(value).replace(/\r?\n|\r/g, ' ').replace(/`/g, "'").replace(/\|/g, '\\|')
  return '`' + text + '`'
}

function table(head: string[], rows: string[][]): string[] {
  return [
    '| ' + head.join(' | ') + ' |',
    '| ' + head.map(() => '---').join(' | ') + ' |',
    ...rows.map((row) => '| ' + row.join(' | ') + ' |'),
    '',
  ]
}

function facts(pairs: [string, string][]): string[] {
  return [...pairs.map(([label, value]) => `- **${label}:** ${value}`), '']
}

export function domainReportMarkdown(data: DomainReport, words: Words): string {
  const { t } = words
  const yesNo = (value: boolean) => t(value ? 'common.yes' : 'common.no')
  const unread = (names: string[]) => [t('findings.unreadable', { sections: names.join(', ') }), '']

  const version = (data as { samadcon_version?: string }).samadcon_version
  const netbios = data.domain.netbios_name ? ` (${cell(data.domain.netbios_name)})` : ''

  const lines: string[] = [
    `# ${t('report.title')}: ${cell(data.domain.dns_domain)}${netbios}`,
    '',
    t('report.made', { dc: cell(data.domain.connected_dc), when: data.generated_at }),
    data.deep ? t('report.wasDeep') : t('report.wasShallow'),
    ...(version ? [`SAMADCON ${cell(version)}`] : []),
    '',
    `## ${t('report.section.connection')}`,
    '',
    ...(data.connection ? connection(data.connection, t, yesNo) : unread(['connection'])),
    `## ${t('report.section.domain')}`,
    '',
    ...domain(data.domain, t, yesNo),
    ...roles(data.roles, t),
    ...controllers(data.controllers, t),
    `## ${t('report.section.password')}`,
    '',
    ...(data.security.policy ? policy(data.security.policy, words) : unread(['policy'])),
    `## ${t('report.section.replication')}`,
    '',
    ...(data.security.replication
      ? replication(data.security.replication, t)
      : unread(['replication'])),
    `## ${t('report.section.accounts')}`,
    '',
    ...(data.security.accounts ? accounts(data.security.accounts, t, yesNo) : unread(['accounts'])),
    `## ${t('report.section.securityFindings')}`,
    '',
    ...findings(data.security.findings, data.security.unreadable, t, unread),
    `## ${t('report.section.policies')}`,
    '',
    ...policies(data.policies.gpos, data.deep, t),
    `## ${t('report.section.policyFindings')}`,
    '',
    ...findings(data.policies.findings, data.policies.unreadable, t, unread),
  ]

  return lines.join('\n').trimEnd() + '\n'
}

type T = Words['t']

function connection(state: ConnectionState, t: T, yesNo: (value: boolean) => string): string[] {
  const ldaps = state.transport === 'ldaps'
  return [
    ...facts([
      [t('diag.transport'), t(ldaps ? 'diag.transport.ldaps' : 'diag.transport.ldap')],
      [t('diag.protection'), cell(state.protection)],
      [t('diag.encrypted'), yesNo(Boolean(state.encrypted))],
      [t('diag.identityVerified'), yesNo(Boolean(state.identity_verified))],
      [
        t('diag.certificate'),
        state.certificate_verified === null
          ? t('diag.certNotInvolved')
          : t(state.certificate_verified ? 'diag.certTrusted' : 'diag.certUntrusted'),
      ],
    ]),
    t(ldaps ? 'diag.identityByTls' : 'diag.identityByKerberos'),
    '',
  ]
}

function domain(summary: DomainSummary, t: T, yesNo: (value: boolean) => string): string[] {
  return facts([
    [t('diag.netbios'), cell(summary.netbios_name)],
    [t('diag.connectedDc'), cell(summary.connected_dc)],
    [
      t('diag.serverSoftware'),
      summary.is_samba
        ? cell(`Samba ${(summary.dc_vendor_version ?? '').split('-')[0]}`.trim())
        : t('diag.serverWindows'),
    ],
    [t('diag.domainLevel'), cell(summary.domain_level_name)],
    [t('diag.forestLevel'), cell(summary.forest_level_name)],
    [t('diag.forestRoot'), yesNo(Boolean(summary.is_forest_root))],
    [t('diag.baseDn'), code(summary.base_dn)],
    [t('diag.domainSid'), code(summary.domain_sid)],
  ])
}

function roles(found: FsmoRole[], t: T): string[] {
  if (found.length === 0) return []
  return [
    `### ${t('diag.roles')}`,
    '',
    ...table(
      [t('diag.role'), t('diag.owner'), t('sites.site'), t('diag.scope')],
      found.map((role) => [
        cell(role.label),
        role.present ? cell(role.owner) : t('diag.notPresent'),
        cell(role.site),
        t(`diag.scope.${role.scope}` as MessageKey),
      ]),
    ),
  ]
}

function controllers(found: DomainController[], t: T): string[] {
  if (found.length === 0) return []
  return [
    `### ${t('diag.controllers')}`,
    '',
    ...table(
      [
        t('sites.name'),
        'DNS',
        t('sites.gc'),
        t('sites.site'),
        t('diag.operatingSystem'),
        t('diag.roles'),
        t('diag.lastLogon'),
      ],
      found.map((dc) => [
        cell(dc.name),
        cell(dc.dns_name),
        t(dc.is_global_catalog ? 'common.yes' : 'common.no'),
        cell(dc.site),
        cell(dc.operating_system),
        cell(dc.roles.join(', ')),
        cell(dc.last_logon),
      ]),
    ),
  ]
}

function policy(found: PasswordPolicy, words: Words): string[] {
  const { t } = words
  const days = (count: number) => words.tn('diag.days' as never, count)
  const minutes = (count: number) => t('sites.minutes', { count })
  const age = (value: number | null) => (value === null ? t('diag.never') : days(value))

  const lines = facts([
    [t('diag.minLength'), cell(found.min_length)],
    [t('diag.history'), cell(found.history_length)],
    [t('diag.maxAge'), age(found.max_age_days)],
    [t('diag.minAge'), found.min_age_days === null ? t('diag.none') : days(found.min_age_days)],
    [t('diag.complexity'), t(found.complexity ? 'common.yes' : 'common.no')],
    [
      t('diag.lockoutThreshold'),
      found.lockout_threshold ? cell(found.lockout_threshold) : t('diag.lockoutDisabled'),
    ],
    [
      t('diag.lockoutDuration'),
      found.lockout_duration_minutes === null
        ? t('diag.untilAdmin')
        : minutes(found.lockout_duration_minutes),
    ],
    [
      t('diag.lockoutWindow'),
      found.lockout_window_minutes === null
        ? t('diag.none')
        : minutes(found.lockout_window_minutes),
    ],
  ])
  if (found.reversible_encryption) lines.push(t('diag.reversibleWarning'), '')

  lines.push(`### ${t('diag.psos')}`, '')
  if (found.password_settings_objects.length === 0) {
    lines.push(t('diag.noPsos'), '')
  } else {
    lines.push(
      ...table(
        [
          t('sites.name'),
          t('diag.precedence'),
          t('diag.minLength'),
          t('diag.maxAge'),
          t('diag.appliesTo'),
        ],
        found.password_settings_objects.map((pso) => [
          cell(pso.name),
          cell(pso.precedence),
          cell(pso.min_length),
          age(pso.max_age_days),
          cell(pso.applies_to.join(', ')),
        ]),
      ),
      t('diag.precedenceHint'),
      '',
    )
  }
  return lines
}

/** The values the account rules were decided from; the rules speak below. */
function accounts(read: AccountExposure, t: T, yesNo: (value: boolean) => string): string[] {
  const unknown = t('report.accounts.unknown')
  return facts([
    [t('report.accounts.krbtgt'), read.krbtgt_password_last_set ?? unknown],
    [t('report.accounts.guest'), read.guest ? yesNo(read.guest.enabled) : unknown],
    [
      t('report.accounts.quota'),
      read.machine_account_quota === null ? unknown : String(read.machine_account_quota),
    ],
    [t('report.accounts.flagged'), String(read.accounts.length) + (read.truncated ? '+' : '')],
  ])
}

function replication(status: ReplicationStatus, t: T): string[] {
  const lines = [t('diag.replicationScope', { dc: cell(status.dc) }), '']
  if (status.unreadable_partitions.length > 0) {
    lines.push(
      t('diag.unreadableReps', { partitions: cell(status.unreadable_partitions.join(', ')) }),
      '',
    )
  }
  if (status.neighbours.length === 0) return [...lines, t('diag.noPartners'), '']

  return [
    ...lines,
    ...table(
      [
        t('diag.partition'),
        t('diag.partner'),
        t('diag.lastSuccess'),
        t('diag.lastAttempt'),
        t('diag.status'),
      ],
      status.neighbours.map((item) => [
        cell(item.partition),
        item.source_dsa ? cell(item.source_dsa) : code(item.source_guid),
        cell(item.last_success),
        cell(item.last_attempt),
        item.result === 0
          ? t('diag.ok')
          : item.result === null
            ? t('diag.unknown')
            : t('diag.failing', { count: item.consecutive_failures }),
      ]),
    ),
  ]
}

function findings(
  found: Finding[],
  unreadable: string[],
  t: T,
  unread: (names: string[]) => string[],
): string[] {
  const lines: string[] = []
  if (unreadable.length > 0) lines.push(...unread(unreadable))
  if (found.length === 0 && unreadable.length === 0) lines.push(t('findings.none'), '')

  for (const finding of found) {
    const evidence = Object.entries(finding.evidence)
    lines.push(
      `### ${t(`findings.${finding.id}` as MessageKey)}`,
      '',
      ...facts([
        [t('report.md.severity'), t(`findings.severity.${finding.severity}` as MessageKey)],
        ...(finding.subject
          ? ([[t('report.md.subject'), cell(finding.subject)]] as [string, string][])
          : []),
      ]),
      t(`findings.${finding.id}.why` as MessageKey),
      '',
    )
    if (evidence.length > 0) {
      lines.push(
        ...evidence.map(([key, value]) => `- ${code(key)} = ${code(evidenceText(value))}`),
        '',
      )
    }
  }
  return lines
}

function evidenceText(value: unknown): string {
  return typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value)
}

function policies(gpos: ReportedGpo[], deep: boolean, t: T): string[] {
  if (gpos.length === 0) return [t('report.noPolicies'), '']

  const half = (label: string, enabled: boolean, extensions: string | null) =>
    `${label}: ${t(!enabled ? 'report.halfDisabled' : extensions ? 'report.halfApplies' : 'report.halfEmpty')}`

  return table(
    [
      t('gpo.name'),
      'GUID',
      t('report.column.links'),
      t('report.column.halves'),
      t('report.column.version'),
      ...(deep ? [t('report.column.sysvol')] : []),
    ],
    gpos.map((gpo) => [
      cell(gpo.display_name || gpo.name),
      cell(gpo.guid),
      gpo.links.length === 0
        ? t('report.noLinks')
        : gpo.links
            .map((link) => {
              const marks = [
                ...(link.enabled ? [] : [t('report.linkDisabled')]),
                ...(link.enforced ? [t('report.linkEnforced')] : []),
              ]
              return cell(link.container) + (marks.length ? ` (${marks.join(', ')})` : '')
            })
            .join('; '),
      half(t('report.machine'), gpo.machine_enabled, gpo.machine_extensions) +
        '; ' +
        half(t('report.user'), gpo.user_enabled, gpo.user_extensions),
      `${gpo.machine_version}/${gpo.user_version}`,
      ...(deep ? [gpo.status ? cell(gpo.status.sysvol_version) : '—'] : []),
    ]),
  )
}

/**
 * A file name from a domain or a policy name and the time it was read.
 * The name comes from the directory, so only plain characters survive.
 */
export function reportFileName(subject: string, readAt: string | null, extension: string): string {
  const plain = subject
    .replace(/[^A-Za-z0-9._-]+/g, '-')
    .replace(/\.{2,}/g, '.')
    .replace(/^[-.]+|[-.]+$/g, '')
  const stamp = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(readAt ?? '')
  const when = stamp ? `-${stamp[1]}${stamp[2]}${stamp[3]}-${stamp[4]}${stamp[5]}` : ''
  return `samadcon-${plain || 'report'}${when}.${extension}`
}
