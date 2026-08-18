/**
 * Shapes returned by the SAMADCON API.
 *
 * Directory objects carry whatever the domain's schema defines, so these types
 * describe the envelope and the fields the UI relies on — not every attribute
 * that may show up.
 */

export type ObjectType =
  | 'user'
  | 'computer'
  | 'group'
  | 'contact'
  | 'organizational_unit'
  | 'container'
  | 'domain'
  | 'builtin'
  | 'gpo'
  | 'printer'
  | 'shared_folder'
  | 'managed_service_account'
  | 'unresolved'
  | 'object'

export interface ApiErrorBody {
  code: string
  message: string
  hint?: string
  detail?: string
  context?: Record<string, unknown>
}

export interface DirectoryObject {
  dn: string
  name: string
  type: ObjectType
  display_name: string | null
  description: string | null
  guid: string | null
  sid?: string
  sam_account_name?: string
  upn?: string | null
  mail?: string | null
  disabled?: boolean
  group_scope?: 'global' | 'domain_local' | 'universal' | null
  security_group?: boolean
  primary_group_member?: boolean
  primary_group?: boolean
  is_container: boolean
  advanced_only: boolean
  when_created: string | null
  when_changed: string | null
}

export interface DomainInfo {
  dc_hostname: string
  base_dn: string
  config_dn: string
  schema_dn: string
  root_domain_dn: string
  domain_sid: string | null
  dns_domain: string
  netbios_name: string
  domain_functional_level: number | null
  forest_functional_level: number | null
}

export interface ConnectionTargetInfo {
  realm: string
  label: string | null
  hosts: string[]
  dns_domain: string | null
  dc_hostname: string | null
  profile_id: string | null
  insecure: boolean
  ca_file: string | null
}

/** How the directory connection is protected, as established at connect time. */
export interface ConnectionState {
  /** "ldap" (Kerberos-encrypted, port 389) or "ldaps" (TLS, port 636). */
  transport: string
  protection: string
  url: string
  encrypted: boolean
  /** null where no certificate is involved — that is not the same as unverified. */
  certificate_verified: boolean | null
  identity_verified: boolean
}

export interface SessionInfo {
  principal: string
  username: string
  realm: string
  csrf_token: string
  expires_at: string
  ticket_expires_at?: string
  created_at?: string
  domain: DomainInfo
  connection?: ConnectionState | null
  target?: ConnectionTargetInfo
}

export interface ServerProfileInfo {
  id: string
  label: string
  hosts: string[]
  realm: string | null
  insecure: boolean
}

export interface ServerListing {
  profiles: ServerProfileInfo[]
  default: { realm: string; hosts: string[]; discovery: 'dns' | 'static' } | null
  allow_custom_servers: boolean
}

/** What a domain controller tells us about itself before we authenticate. */
export interface ProbeResult {
  host: string
  dc_hostname: string | null
  realm: string
  dns_domain: string
  base_dn: string
  transport: 'ldap' | 'ldaps'
  supports_gssapi: boolean
  is_domain_controller: boolean
  ldaps_reachable: boolean
  ldaps_certificate_trusted: boolean | null
  /** Whether the container can resolve the DC's own name — Kerberos needs it. */
  dc_hostname_resolves: boolean | null
  domain_functional_level: number | null
  forest_functional_level: number | null
  /** True when LDAPS answers but its certificate does not validate. */
  requires_insecure: boolean
}

export interface LoginOptions {
  server?: string
  realm?: string
  profileId?: string
  insecure?: boolean
}

export interface ChildListing {
  parent: string
  entries: DirectoryObject[]
  truncated: boolean
}

export interface SearchResult {
  base: string
  entries: DirectoryObject[]
  truncated: boolean
}

export interface TreeNode extends DirectoryObject {
  /** null when the server did not determine it — assume it might have some. */
  has_children: boolean | null
}

export interface TreeListing {
  parent: string
  nodes: TreeNode[]
}

export interface AccountStatus {
  disabled: boolean
  locked_out: boolean
  lockout_time: string | null
  last_logon: string | null
  logon_count: number
  bad_password_count: number
  bad_password_time: string | null
  must_change_password: boolean
  password_last_set: string | null
  password_expires: string | null
  account_expires: string | null
}

export interface UserDetail extends DirectoryObject {
  sam_account_name: string
  attributes: Record<string, string | null>
  flags: Record<string, boolean>
  user_account_control: number
  status: AccountStatus
  member_of: string[]
  direct_reports: string[]
  primary_group_id: number | null
}

export interface GroupDetail extends DirectoryObject {
  sam_account_name: string
  attributes: Record<string, string | null>
  scope: 'global' | 'domain_local' | 'universal' | null
  security_group: boolean
  group_type: number | null
  member_count: number
  member_of: string[]
}

export interface ComputerDetail extends DirectoryObject {
  sam_account_name: string
  attributes: Record<string, string | null>
  flags: Record<string, boolean>
  role: string
  operating_system: { name: string | null; version: string | null; service_pack: string | null }
  status: { disabled: boolean; last_logon: string | null; password_last_set: string | null }
  service_principal_names: string[]
  member_of: string[]
}

export interface OuDetail extends DirectoryObject {
  attributes: Record<string, string | null>
  gp_link: string | null
  block_inheritance: boolean
  child_count: number
  delete_protected: boolean | null
}

export interface AttributeValue {
  text?: string
  /** base64; present instead of `text` for values that are not valid UTF-8. */
  binary?: string
  size?: number
}

export interface AttributeEntry {
  values: AttributeValue[]
  /** False for directory-managed attributes and for binary values. */
  editable: boolean
}

export interface AttributeListing {
  dn: string
  attributes: Record<string, AttributeEntry>
}

// --- DNS -------------------------------------------------------------------

export interface DnsZone {
  dn: string
  name: string
  partition: 'domain' | 'forest' | 'legacy'
  reverse: boolean
  guid: string | null
  when_changed: string | null
}

export type DnsRecordType = 'A' | 'AAAA' | 'CNAME' | 'NS' | 'PTR' | 'MX' | 'SRV' | 'TXT' | 'SOA'

/** Type-specific payload; which keys are present depends on the record type. */
export interface DnsRecordData {
  address?: string
  target?: string
  preference?: number
  exchange?: string
  priority?: number
  weight?: number
  port?: number
  strings?: string[]
  [key: string]: unknown
}

export interface DnsRecord {
  /** Name relative to the zone; '@' is the zone itself. */
  node: string
  /** Fully qualified name. */
  name: string
  type: DnsRecordType | string
  ttl: number
  serial: number
  timestamp: number
  tombstone: boolean
  editable: boolean
  data: DnsRecordData
  display: string
  dn: string
  index: number
}

export interface DnsRecordListing {
  zone: string
  zone_dn: string
  records: DnsRecord[]
}

export interface DnsRecordTypeInfo {
  type: string
  fields: string[]
}

export interface Trustee {
  sid: string
  name: string
  kind: string
  dn?: string
}

export interface ObjectGuidRef {
  guid: string
  kind: 'extended_right' | 'schema' | 'unknown'
  name: string
}

export interface AccessControlEntry {
  index: number
  type: 'allow' | 'deny'
  inherited: boolean
  applies_to_children: boolean
  inherit_only: boolean
  trustee: Trustee
  mask: number
  rights: string[]
  full_control: boolean
  /** The extended right, class or attribute this entry is limited to. */
  object?: ObjectGuidRef
  /** The object class the entry is inherited to. */
  applies_to?: ObjectGuidRef
}

export interface AclListing {
  dn: string
  owner: Trustee | null
  aces: AccessControlEntry[]
  /** Passed back on write so a concurrent change is detected. */
  sddl: string
  inheritance_blocked: boolean
}

export interface DelegationTemplate {
  id: string
  container_only: boolean
  ace_count: number
}

export interface MemberListing {
  dn: string
  members: DirectoryObject[]
  recursive: boolean
}

export interface ServerInfo {
  version: string
  realm: string
  workgroup: string
  dc_hosts: string[] | null
  dc_discovery: 'dns' | 'static'
  ldap_insecure: boolean
  sessions: { active: number; workers: number; idle_timeout_minutes: number }
}

// ---------------------------------------------------------------------------
// Sites and services
// ---------------------------------------------------------------------------

export interface SiteServer {
  dn: string
  name: string
  dns_name: string | null
  computer_dn: string | null
  is_dc: boolean
  ntds_dn: string | null
  is_global_catalog: boolean
  functional_level?: number | null
  guid?: string | null
}

export interface Site {
  dn: string
  name: string
  description: string | null
  location: string | null
  server_count?: number
  subnet_count?: number
  /** Filled in by the topology call and by the site detail. */
  servers?: SiteServer[]
  subnets?: Subnet[]
  settings?: SiteSettings
}

export interface SiteSettings {
  present: boolean
  options?: number
  /** The server the KCC elected to build the inter-site topology. */
  topology_generator?: string | null
  auto_topology_disabled?: boolean
  inter_site_auto_topology_disabled?: boolean
}

export interface Subnet {
  dn: string
  name: string
  description: string | null
  location: string | null
  site_dn: string | null
  site: string | null
}

export interface SiteLink {
  dn: string
  name: string
  description: string | null
  transport: 'IP' | 'SMTP' | string
  cost: number
  /** Minutes between replication attempts. */
  replication_interval: number
  notify: boolean
  site_dns: string[]
  sites: string[]
}

export interface Topology {
  sites: Site[]
  subnets: Subnet[]
  links: SiteLink[]
  sites_dn: string
}

export interface ReplicationConnection {
  dn: string
  name: string
  from_server: string | null
  from_site: string | null
  /** Built by the KCC rather than by an administrator. */
  generated: boolean
  notify: boolean
  enabled: boolean
}

// ---------------------------------------------------------------------------
// Diagnostics
// ---------------------------------------------------------------------------

export interface FsmoRole {
  role: string
  label: string
  scope: 'domain' | 'forest'
  object_dn: string
  owner_dn: string | null
  owner: string | null
  site: string | null
  present: boolean
}

export interface DomainController extends SiteServer {
  site: string
  site_dn: string
  roles: string[]
  operating_system: string | null
  last_logon: string | null
}

export interface ReplicationNeighbour {
  partition: string
  partition_dn: string
  source_dsa: string | null
  source_guid: string
  last_attempt: string | null
  last_success: string | null
  /** 0 means the last attempt succeeded; null means it could not be read. */
  result: number | null
  consecutive_failures: number
}

export interface ReplicationStatus {
  dc: string
  neighbours: ReplicationNeighbour[]
  failing: number
  healthy: boolean
  unreadable_partitions: string[]
}

export interface PasswordSettingsObject {
  dn: string
  name: string
  precedence: number | null
  min_length: number | null
  history_length: number | null
  complexity: boolean | null
  min_age_days: number | null
  max_age_days: number | null
  lockout_threshold: number | null
  lockout_duration_minutes: number | null
  lockout_window_minutes: number | null
  applies_to: string[]
  applies_to_dns: string[]
}

export interface PasswordPolicy {
  min_length: number | null
  history_length: number | null
  min_age_days: number | null
  max_age_days: number | null
  complexity: boolean
  reversible_encryption: boolean
  lockout_threshold: number | null
  lockout_duration_minutes: number | null
  lockout_window_minutes: number | null
  password_settings_objects: PasswordSettingsObject[]
}

export interface ProblemAccount {
  dn: string
  name: string
  display_name: string | null
  lockout_time: string | null
  expires: string | null
  password_last_set: string | null
  last_logon: string | null
  must_change_password: boolean
}

export interface AccountProblems {
  locked: ProblemAccount[]
  disabled: ProblemAccount[]
  expired: ProblemAccount[]
  truncated: boolean
  lockout_duration_minutes: number | null
}

export interface DomainSummary {
  dns_domain: string
  netbios_name: string
  base_dn: string
  domain_sid: string | null
  connected_dc: string
  domain_level: number | null
  domain_level_name: string | null
  forest_level: number | null
  forest_level_name: string | null
  is_forest_root: boolean
}

export interface DiagnosticsOverview {
  domain: DomainSummary
  roles: FsmoRole[]
  controllers: DomainController[]
  replication: ReplicationStatus
  policy: PasswordPolicy
}

// ---------------------------------------------------------------------------
// Group policy
// ---------------------------------------------------------------------------

export interface Gpo {
  dn: string
  /** The GUID in braces — what links point at. */
  guid: string
  name: string
  display_name: string | null
  /** UNC path of the SYSVOL half. */
  path: string | null
  version: number
  machine_version: number
  user_version: number
  machine_enabled: boolean
  user_enabled: boolean
  flags: number
  /** Registered client-side extensions; empty means the policy carries nothing. */
  machine_extensions: string | null
  user_extensions: string | null
  wmi_filter: string | null
  created: string | null
  changed: string | null
}

export interface GpoStatus {
  directory_version: number
  sysvol_version: number | null
  sysvol_present: boolean
  consistent: boolean
  /** Empty when both halves agree; otherwise what does not line up. */
  problems: string[]
  /** Correct but surprising states. They never make a policy inconsistent. */
  notes?: string[]
}

export interface GpoLink {
  dn: string
  guid: string
  display_name: string | null
  /** 1 takes precedence, as GPMC counts it. */
  order: number
  options: number
  enabled: boolean
  enforced: boolean
  /** The link points at a policy that no longer exists. */
  missing: boolean
}

export interface GpoLinkListing {
  dn: string
  name: string
  links: GpoLink[]
  block_inheritance: boolean
}

export interface GpoLinkLocation {
  container: string
  container_dn: string
  kind: 'domain' | 'organizational_unit' | 'site' | 'container'
  order: number
  enabled: boolean
  enforced: boolean
}

export interface AppliedGpo extends GpoLink {
  source: string
  source_dn: string
  depth: number
  precedence?: number
  /** Only on excluded entries: why it does not apply. */
  reason?: 'blocked' | 'disabled' | 'missing'
}

export interface GpoInheritance {
  dn: string
  chain: { name: string; dn: string; blocked: boolean }[]
  applied: AppliedGpo[]
  excluded: AppliedGpo[]
}

export interface GpoFilterEntry {
  trustee: Trustee
  inherited: boolean
  read: boolean
  apply: boolean
}

export interface GpoFiltering {
  dn: string
  applies_to: GpoFilterEntry[]
  /** Read without apply, or the other way round — always a mistake. */
  incomplete: GpoFilterEntry[]
  sddl: string
}

export interface RegistryValue {
  index: number
  key: string
  value: string
  type: string
  type_id: number
  size: number
  data: string | number | string[]
  display: string
}

export interface RegistryGroup {
  key: string
  values: RegistryValue[]
}

export interface GpoHalfReport {
  registry: RegistryGroup[]
  registry_count: number
  /** Section name -> name/value pairs, straight out of GptTmpl.inf. */
  security: Record<string, { name: string; value: string }[]>
  /** Section name -> scripts, each with cmdline and parameters. */
  scripts: Record<string, Record<string, string>[]>
  /**
   * Folder redirection, user configuration only — read-only for now, so it is
   * reported here rather than given an editor that could not save.
   */
  redirection: {
    folders?: {
      guid: string
      trustees: string[]
      targets: { sid: string; path: string; options: Record<string, string> }[]
    }[]
  }
  preferences: {
    type: string
    file: string
    items: {
      element: string
      attributes: Record<string, string>
      filters: { element: string; attributes: Record<string, string> }[]
      properties?: { element: string; attributes: Record<string, string> }[]
    }[]
  }[]
  /**
   * Samba policy manifests. `entries` is what the policy holds — empty is a
   * normal state, since samba-tool leaves the file behind when the last entry
   * is removed rather than deleting it.
   */
  vgp: {
    path: string
    name: string
    description: string
    entries: { element: string; fields: { name: string; value: string }[]; text: string }[]
  }[]
  other_files: { path: string; name: string }[]
}

export interface GpoReport {
  gpo: Gpo
  status: GpoStatus
  machine: GpoHalfReport
  user: GpoHalfReport
  /** Files that are there but could not be read — never silently dropped. */
  unreadable: { path: string; reason: string }[]
  empty?: boolean
}

export interface WmiFilter {
  dn: string | null
  id: string
  name: string | null
  description?: string | null
  queries: { namespace: string; query: string }[]
  author?: string | null
  created?: string | null
  changed?: string | null
  /** The policy points at a filter that no longer exists. */
  missing?: boolean
}

// ---------------------------------------------------------------------------
// Administrative templates
// ---------------------------------------------------------------------------

export interface AdmxStore {
  present: boolean
  path: string
  templates: { name: string; size: number }[]
  languages: string[]
  language: string | null
}

/** Templates shipped inside the image, ready to be copied into the store. */
export interface AdmxBundled {
  present: boolean
  path: string
  /** File names, e.g. "samba.admx" — no sizes: nothing has been read yet. */
  templates: string[]
  languages: string[]
}

export interface AdmxCategory {
  id: string
  name: string
  display_name: string
  explain: string
  parent: string | null
  child_count: number
  policy_count: number
  /** False means no expander — the same rule as the directory tree. */
  has_children: boolean
}

export interface AdmxPolicySummary {
  id: string
  name: string
  display_name: string
  class: 'Machine' | 'User' | 'Both'
  halves: string[]
  category: string | null
  source: string
  has_elements: boolean
  /** Only present when the listing was asked about a particular GPO. */
  state?: PolicyState
}

export interface AdmxElement {
  id: string
  kind: 'boolean' | 'decimal' | 'longDecimal' | 'text' | 'enum' | 'list' | 'multiText'
  required: boolean
  min?: number | null
  max?: number | null
  max_length?: number | null
  items?: { index: number; label: string }[]
  /** Lists come in two shapes: plain entries, or name/value pairs. */
  explicit_value?: boolean
  additive?: boolean
}

/** One control of the form, as the ADML describes it. */
export interface AdmxControl {
  kind: string
  ref: string | null
  label?: string
  text?: string
  default?: string | boolean
  default_item?: number
}

export interface AdmxPolicy extends AdmxPolicySummary {
  explain: string
  key: string
  value_name: string | null
  /** Null when the template names no requirement, or names one we cannot resolve. */
  supported_on: string | null
  elements: AdmxElement[]
  presentation: AdmxControl[]
}

export interface AdmxTree {
  category: string | null
  path: { id: string; display_name: string }[]
  categories: AdmxCategory[]
  policies: AdmxPolicySummary[]
  language: string
}

export type PolicyState = 'not_configured' | 'enabled' | 'disabled'

export interface AdmxState {
  gpo: string
  policy: string
  half: string
  /** Passed back when saving so a concurrent change is refused. */
  version: number
  state: PolicyState
  values: Record<string, unknown>
}

export interface AdmxApplyResult {
  dn: string
  changed: boolean
  version: number
  written?: number
  removed?: number
}

// ---------------------------------------------------------------------------
// Scripts
// ---------------------------------------------------------------------------

export type ScriptEngine = 'cmd' | 'powershell'
export type ScriptEvent = 'Startup' | 'Shutdown' | 'Logon' | 'Logoff'

export interface ScriptEntry {
  engine: ScriptEngine
  command: string
  parameters: string
}

// ---------------------------------------------------------------------------
// Samba's own policies (VGP)
// ---------------------------------------------------------------------------

export type VgpPolicy =
  | 'sudoers'
  | 'symlink'
  | 'files'
  | 'motd'
  | 'issue'
  | 'openssh'
  | 'access_allow'
  | 'access_deny'

/** A file sitting beside a policy's manifest, ready for an entry to name it. */
export interface VgpPayload {
  name: string
  size: number
}

/** Each kind has its own entry shape; the tab picks an editor per kind. */
export type VgpEntry = Record<string, unknown>

export interface VgpKind {
  id: VgpPolicy
  path: string
  name: string
  description: string
}

export interface GpoVgp {
  dn: string
  /** Passed back when saving so a concurrent change is refused. */
  version_number: number
  policies: Record<string, { present: boolean; entries: VgpEntry[] }>
}

// ---------------------------------------------------------------------------
// Group policy preferences
// ---------------------------------------------------------------------------

export type PreferenceTypeId =
  | 'drives'
  | 'registry'
  | 'files'
  | 'folders'
  | 'shortcuts'
  | 'environment'
  | 'printers'

/** Create, Replace, Update, Delete — the letters the file carries. */
export type PreferenceAction = 'C' | 'R' | 'U' | 'D'

export interface PreferenceField {
  name: string
  kind: 'text' | 'bool' | 'choice'
  default: string
  choices: string[]
}

/**
 * One kind of element inside a preference file. Every type has exactly one
 * except printers, where a shared, a port and a local printer share a file
 * and do not share a half.
 */
export interface PreferenceKind {
  id: string
  halves: string[]
  /** A service has none: it carries a startup type and a service action. */
  has_action: boolean
  /** False for scheduled tasks — read and edited here, created in GPMC. */
  creatable: boolean
  fields: PreferenceField[]
}

/** One member of a local group. */
export interface PreferenceMember {
  name: string
  action: 'ADD' | 'REMOVE'
  sid?: string
}

export interface PreferenceType {
  id: PreferenceTypeId
  halves: string[]
  kinds: PreferenceKind[]
}

export interface PreferenceItem {
  kind: string
  uid: string
  name: string
  /** Usually the name; an environment variable adds its value, a local
   *  printer shows its location instead. Derived by the server. */
  status: string
  image: number
  changed: string
  action: PreferenceAction | ''
  properties: Record<string, string>
  /** The lines of a REG_MULTI_SZ; empty for everything else. */
  values: string[]
  /** The members of a local group; empty for everything else. */
  members: PreferenceMember[]
  bypass_errors: boolean
  user_context: boolean
  /** An encrypted password already in the file. Never set from here. */
  has_password: boolean
  /**
   * Item-level targeting, read only. It is not sent back when saving — the
   * server carries it over from the file by uid, so editing an item cannot
   * drop the filter that decides who it applies to.
   */
  filter_names: string[]
}

export interface GpoPreferences {
  dn: string
  version_number: number
  types: Record<string, { halves: Record<string, { present: boolean; items: PreferenceItem[] }> }>
}

// ---------------------------------------------------------------------------
// Security settings
// ---------------------------------------------------------------------------

export type SecurityKind = 'number' | 'switch' | 'audit' | 'trustees'

export interface SecuritySetting {
  group: string
  section: string
  key: string
  kind: SecurityKind
  min: number | null
  max: number | null
  unit: string | null
}

export interface SecurityCatalogue {
  groups: { id: string; section: string }[]
  settings: SecuritySetting[]
  restricted_groups: {
    section: string
    members_suffix: string
    memberof_suffix: string
  }
}

/** A resolved account, the same shape the ACL editor uses. */
export interface SecurityTrustee {
  sid: string
  name: string
  kind: string
  dn?: string
}

export interface GpoSecurity {
  dn: string
  present: boolean
  /** Passed back when saving so a concurrent change is refused. */
  version_number: number
  registered: boolean
  /**
   * Section name -> key -> value. A plain setting is a string; a user right
   * or a restricted group's members come back as resolved accounts.
   */
  sections: Record<string, Record<string, string | SecurityTrustee[]>>
}

// ---------------------------------------------------------------------------
// Folder redirection
// ---------------------------------------------------------------------------

export interface RedirectionTarget {
  sid: string
  path: string
  /** Carried verbatim — `Flags` above all, whose bits are not documented. */
  options: Record<string, string>
}

export interface RedirectedFolder {
  guid: string
  trustees: string[]
  targets: RedirectionTarget[]
}

export interface GpoRedirection {
  dn: string
  /** False when the policy has no fdeploy1.ini yet. */
  present: boolean
  /** Passed back when saving so a concurrent change is refused. */
  version_number: number
  /** Whether the extension that applies redirection is registered. */
  registered: boolean
  folders: RedirectedFolder[]
  version: Record<string, string>
  other: Record<string, Record<string, string>>
}

export interface GpoScripts {
  dn: string
  half: string
  /** Passed back when saving so a concurrent change is refused. */
  version: number
  events: Record<string, ScriptEntry[]>
  /** Whether PowerShell runs first; null when the file does not say. */
  ps_first: boolean | null
  /** Whether the extension that runs them is registered on this half. */
  registered: boolean
}
