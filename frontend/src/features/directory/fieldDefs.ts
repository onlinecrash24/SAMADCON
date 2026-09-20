/**
 * The editable fields, by API name.
 *
 * The names are the API's, not LDAP's — the backend maps them (USER_FIELDS
 * and friends) and rejects anything it does not know. Which tab a field is on
 * is decided by the tab, in sheet/tabs; this is only what each field is.
 *
 * Labels are i18n keys, because the server has no business knowing about
 * those.
 */

import type { ObjectType } from '../../api/types'
import type { MessageKey } from '../../i18n/messages'

/**
 * 'upn' is name plus a suffix chosen from the forest (UpnField); 'dn' is a
 * reference to another object, picked rather than typed (DnField).
 */
export type FieldKind = 'text' | 'email' | 'tel' | 'url' | 'multiline' | 'upn' | 'dn'

export interface FieldDef {
  /** API field name, sent verbatim in the attributes object. */
  name: string
  label: MessageKey
  kind?: FieldKind
  /** Free-form note shown under the input. */
  hint?: MessageKey
  maxLength?: number
  /** For kind 'dn': what the picker offers. */
  pickTypes?: ObjectType[]
}

const def = (name: string, label: MessageKey, rest: Omit<FieldDef, 'name' | 'label'> = {}): FieldDef => ({
  name,
  label,
  ...rest,
})

export const FIELDS = {
  // General
  first_name: def('first_name', 'user.firstName'),
  initials: def('initials', 'user.initials', { maxLength: 6 }),
  last_name: def('last_name', 'user.lastName'),
  display_name: def('display_name', 'user.displayName'),
  description: def('description', 'user.description'),
  office: def('office', 'user.office'),
  telephone: def('telephone', 'user.telephone', { kind: 'tel' }),
  mail: def('mail', 'user.mail', { kind: 'email' }),
  web_page: def('web_page', 'user.webPage', { kind: 'url' }),
  // Account
  upn: def('upn', 'user.upn', { kind: 'upn', hint: 'user.upnHint' }),
  logon_workstations: def('logon_workstations', 'user.logonWorkstations', {
    hint: 'user.logonWorkstationsHint',
  }),
  // Address
  street: def('street', 'user.street', { kind: 'multiline' }),
  post_office_box: def('post_office_box', 'user.postOfficeBox'),
  city: def('city', 'user.city'),
  state: def('state', 'user.state'),
  postal_code: def('postal_code', 'user.postalCode'),
  country: def('country', 'user.country', { hint: 'user.countryHint', maxLength: 2 }),
  // Telephones
  home_phone: def('home_phone', 'user.homePhone', { kind: 'tel' }),
  pager: def('pager', 'user.pager', { kind: 'tel' }),
  mobile: def('mobile', 'user.mobile', { kind: 'tel' }),
  fax: def('fax', 'user.fax', { kind: 'tel' }),
  ip_phone: def('ip_phone', 'user.ipPhone'),
  notes: def('notes', 'user.notes', { kind: 'multiline' }),
  // Profile
  profile_path: def('profile_path', 'user.profilePath'),
  logon_script: def('logon_script', 'user.logonScript'),
  home_directory: def('home_directory', 'user.homeDirectory'),
  home_drive: def('home_drive', 'user.homeDrive', { maxLength: 2 }),
  // Organization
  title: def('title', 'user.title'),
  department: def('department', 'user.department'),
  company: def('company', 'user.company'),
  manager: def('manager', 'user.manager', { kind: 'dn', pickTypes: ['user', 'contact'] }),
  // Groups, computers, OUs
  managed_by: def('managed_by', 'group.managedBy', {
    kind: 'dn',
    pickTypes: ['user', 'group', 'contact'],
  }),
  location: def('location', 'computer.location'),
  dns_host_name: def('dns_host_name', 'computer.dnsName'),
} satisfies Record<string, FieldDef>

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

/** Whether a property sheet exists for this type at all. */
export function isEditable(type: string): boolean {
  return (
    type === 'user' ||
    type === 'managed_service_account' ||
    type === 'group' ||
    type === 'computer' ||
    type === 'organizational_unit'
  )
}
