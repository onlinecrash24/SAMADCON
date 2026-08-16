/**
 * Which fields each object type shows, in which order, under which heading.
 *
 * The field names are the API's, not LDAP's — the backend maps them (see
 * USER_FIELDS and friends) and rejects anything it does not know. Layout lives
 * here rather than on the server because it is presentation: the labels are
 * i18n keys, and the server has no business knowing about those.
 */

import type { MessageKey } from '../../i18n/messages'

export type FieldKind = 'text' | 'email' | 'tel' | 'url' | 'multiline'

export interface FieldDef {
  /** API field name, sent verbatim in the attributes object. */
  name: string
  label: MessageKey
  kind?: FieldKind
  /** Free-form note shown under the input. */
  hint?: MessageKey
  maxLength?: number
}

export interface FieldGroup {
  title: MessageKey
  fields: FieldDef[]
}

export const USER_GROUPS: FieldGroup[] = [
  {
    title: 'detail.general',
    fields: [
      { name: 'first_name', label: 'user.firstName' },
      { name: 'last_name', label: 'user.lastName' },
      { name: 'initials', label: 'user.initials', maxLength: 6 },
      { name: 'display_name', label: 'user.displayName' },
      { name: 'description', label: 'user.description' },
      { name: 'office', label: 'user.office' },
      { name: 'mail', label: 'user.mail', kind: 'email' },
      { name: 'web_page', label: 'user.webPage', kind: 'url' },
    ],
  },
  {
    title: 'detail.account',
    fields: [
      // sAMAccountName is deliberately absent: changing it is a rename in all
      // but name and belongs with the rename action, not a text field.
      { name: 'upn', label: 'user.upn', hint: 'user.upnHint' },
      { name: 'logon_workstations', label: 'user.logonWorkstations', hint: 'user.logonWorkstationsHint' },
    ],
  },
  {
    title: 'detail.address',
    fields: [
      { name: 'street', label: 'user.street', kind: 'multiline' },
      { name: 'post_office_box', label: 'user.postOfficeBox' },
      { name: 'city', label: 'user.city' },
      { name: 'state', label: 'user.state' },
      { name: 'postal_code', label: 'user.postalCode' },
      { name: 'country', label: 'user.country', hint: 'user.countryHint', maxLength: 2 },
    ],
  },
  {
    title: 'detail.telephones',
    fields: [
      { name: 'telephone', label: 'user.telephone', kind: 'tel' },
      { name: 'mobile', label: 'user.mobile', kind: 'tel' },
      { name: 'home_phone', label: 'user.homePhone', kind: 'tel' },
      { name: 'pager', label: 'user.pager', kind: 'tel' },
      { name: 'fax', label: 'user.fax', kind: 'tel' },
      { name: 'ip_phone', label: 'user.ipPhone' },
      { name: 'notes', label: 'user.notes', kind: 'multiline' },
    ],
  },
  {
    title: 'detail.profile',
    fields: [
      { name: 'profile_path', label: 'user.profilePath' },
      { name: 'logon_script', label: 'user.logonScript' },
      { name: 'home_directory', label: 'user.homeDirectory' },
      { name: 'home_drive', label: 'user.homeDrive', maxLength: 2 },
    ],
  },
  {
    title: 'detail.organization',
    fields: [
      { name: 'title', label: 'user.title' },
      { name: 'department', label: 'user.department' },
      { name: 'company', label: 'user.company' },
      { name: 'manager', label: 'user.manager', hint: 'user.managerHint' },
    ],
  },
]

export const GROUP_GROUPS: FieldGroup[] = [
  {
    title: 'detail.general',
    fields: [
      { name: 'display_name', label: 'user.displayName' },
      { name: 'description', label: 'user.description' },
      { name: 'mail', label: 'user.mail', kind: 'email' },
      { name: 'notes', label: 'user.notes', kind: 'multiline' },
      { name: 'managed_by', label: 'group.managedBy', hint: 'user.managerHint' },
    ],
  },
]

export const COMPUTER_GROUPS: FieldGroup[] = [
  {
    title: 'detail.general',
    fields: [
      { name: 'display_name', label: 'user.displayName' },
      { name: 'description', label: 'user.description' },
      { name: 'location', label: 'computer.location' },
      { name: 'dns_host_name', label: 'computer.dnsName' },
      { name: 'managed_by', label: 'group.managedBy', hint: 'user.managerHint' },
    ],
  },
]

export const OU_GROUPS: FieldGroup[] = [
  {
    title: 'detail.general',
    fields: [
      { name: 'description', label: 'user.description' },
      { name: 'street', label: 'user.street', kind: 'multiline' },
      { name: 'city', label: 'user.city' },
      { name: 'state', label: 'user.state' },
      { name: 'postal_code', label: 'user.postalCode' },
      { name: 'country', label: 'user.country', hint: 'user.countryHint', maxLength: 2 },
      { name: 'managed_by', label: 'group.managedBy', hint: 'user.managerHint' },
    ],
  },
]

/** Account options that may be toggled, in the order ADUC shows them. */
export const ACCOUNT_FLAGS: string[] = [
  'account_disabled',
  'password_never_expires',
  'smartcard_required',
  'not_delegated',
  'trusted_for_delegation',
  'password_not_required',
  'no_preauth_required',
  'use_des_key_only',
  'encrypted_text_password_allowed',
  'home_directory_required',
]

/**
 * Options that weaken the account's security. Flagged in the UI so nobody
 * enables one without noticing — this mirrors samadcon.ad.uac.DANGEROUS_FLAGS.
 */
export const DANGEROUS_FLAGS = new Set([
  'password_not_required',
  'no_preauth_required',
  'trusted_for_delegation',
  'use_des_key_only',
  'encrypted_text_password_allowed',
])

export function groupsForType(type: string): FieldGroup[] {
  switch (type) {
    case 'user':
    case 'managed_service_account':
      return USER_GROUPS
    case 'group':
      return GROUP_GROUPS
    case 'computer':
      return COMPUTER_GROUPS
    case 'organizational_unit':
      return OU_GROUPS
    default:
      return []
  }
}
