/** Typed wrappers around the API routes. */

import { dnParam, http } from './client'
import type {
  AccountProblems,
  AclListing,
  AdmxApplyResult,
  AdmxPolicy,
  AdmxPolicySummary,
  AdmxState,
  AdmxBundled,
  AdmxStore,
  AdmxTree,
  AssistantPayload,
  AssistantReport,
  AssistantStatus,
  AttributeListing,
  ChildListing,
  ComputerDetail,
  DelegationTemplate,
  DiagnosticsOverview,
  DnsRecord,
  DnsRecordData,
  DnsRecordListing,
  DnsRecordTypeInfo,
  DnsZone,
  DomainReport,
  FindingArea,
  FindingsReport,
  RegistrationDifferences,
  ScriptFile,
  DirectoryObject,
  Gpo,
  GpoFiltering,
  GpoPreferences,
  GpoInheritance,
  GpoLinkListing,
  GpoLinkLocation,
  GpoRedirection,
  GpoReport,
  GpoScripts,
  GpoStatus,
  GroupDetail,
  LoginOptions,
  MemberListing,
  OllamaModel,
  OuDetail,
  PasswordPolicy,
  PolicyState,
  PreferenceAction,
  PreferenceMember,
  PreferenceType,
  PreferenceTypeId,
  ProbeResult,
  ReplicationConnection,
  GpoSecurity,
  GpoVgp,
  ScriptEngine,
  ScriptEvent,
  SearchResult,
  SecurityCatalogue,
  ServerInfo,
  ServerListing,
  SessionInfo,
  Site,
  SiteLink,
  SiteServer,
  Subnet,
  Topology,
  TreeListing,
  UserDetail,
  VgpEntry,
  VgpKind,
  VgpPayload,
  VgpPolicy,
  WmiFilter,
} from './types'

export const api = {
  // -- system ------------------------------------------------------------
  info: () => http.get<ServerInfo>('/info'),

  // -- servers -----------------------------------------------------------
  servers: () => http.get<ServerListing>('/servers'),
  /** Identify the domain behind an address, before signing in. */
  probeServer: (host: string, options: { insecure?: boolean; profileId?: string } = {}) =>
    http.post<ProbeResult>('/servers/probe', {
      host,
      insecure: options.insecure ?? false,
      profile_id: options.profileId ?? null,
    }),

  // -- auth --------------------------------------------------------------
  login: (username: string, password: string, options: LoginOptions = {}) =>
    http.post<SessionInfo>('/auth/login', {
      username,
      password,
      server: options.server ?? null,
      realm: options.realm ?? null,
      profile_id: options.profileId ?? null,
      insecure: options.insecure ?? false,
    }),
  logout: () => http.post<{ status: string }>('/auth/logout'),
  session: () => http.get<SessionInfo>('/auth/session'),
  whoami: () => http.get<DirectoryObject & { member_of: DirectoryObject[] }>('/auth/whoami'),

  // -- navigation --------------------------------------------------------
  roots: () =>
    http.get<{ roots: Array<{ dn: string; label: string; kind: string; exists: boolean }> }>(
      '/directory/roots',
    ),
  tree: (dn: string, advanced = false) =>
    http.get<TreeListing>(`/directory/tree?dn=${dnParam(dn)}&advanced=${advanced}`),
  children: (dn: string, options: { types?: string[]; query?: string; advanced?: boolean } = {}) => {
    const params = new URLSearchParams({ dn })
    if (options.types?.length) params.set('types', options.types.join(','))
    if (options.query) params.set('q', options.query)
    if (options.advanced) params.set('advanced', 'true')
    return http.get<ChildListing>(`/directory/children?${params.toString()}`)
  },
  search: (query: string, options: { base?: string; types?: string[] } = {}) => {
    const params = new URLSearchParams()
    if (query) params.set('q', query)
    if (options.base) params.set('base', options.base)
    if (options.types?.length) params.set('types', options.types.join(','))
    return http.get<SearchResult>(`/directory/search?${params.toString()}`)
  },
  object: (dn: string) => http.get<DirectoryObject>(`/directory/object?dn=${dnParam(dn)}`),
  path: (dn: string) =>
    http.get<{ dn: string; path: DirectoryObject[] }>(`/directory/object/path?dn=${dnParam(dn)}`),
  attributes: (dn: string) =>
    http.get<AttributeListing>(`/directory/object/attributes?dn=${dnParam(dn)}`),
  /** Values are replaced; null removes the attribute. */
  updateAttributes: (dn: string, attributes: Record<string, string | string[] | null>) =>
    http.patch<{ dn: string; applied: Record<string, unknown> }>(
      `/directory/object/attributes?dn=${dnParam(dn)}`,
      { attributes },
    ),

  // -- generic object operations ----------------------------------------
  move: (dn: string, targetDn: string) =>
    http.post<{ dn: string; previous_dn: string }>(`/directory/object/move?dn=${dnParam(dn)}`, {
      target_dn: targetDn,
    }),
  rename: (dn: string, name: string) =>
    http.post<{ dn: string; previous_dn: string }>(`/directory/object/rename?dn=${dnParam(dn)}`, {
      name,
    }),
  remove: (dn: string, recursive = false) =>
    http.delete<{ dn: string; deleted: boolean }>(
      `/directory/object?dn=${dnParam(dn)}&recursive=${recursive}`,
    ),

  // -- users -------------------------------------------------------------
  user: (dn: string) => http.get<UserDetail>(`/users?dn=${dnParam(dn)}`),
  createUser: (payload: {
    parent_dn: string
    sam_account_name: string
    common_name?: string
    password?: string
    must_change_password?: boolean
    enabled?: boolean
    attributes?: Record<string, string>
  }) => http.post<UserDetail>('/users', payload),
  updateUser: (dn: string, payload: { attributes?: Record<string, string | null>; flags?: Record<string, boolean> }) =>
    http.patch<{ dn: string; applied: Record<string, unknown> }>(`/users?dn=${dnParam(dn)}`, payload),
  setPassword: (dn: string, password: string, mustChange: boolean) =>
    http.post<{ dn: string }>(`/users/password?dn=${dnParam(dn)}`, {
      password,
      must_change: mustChange,
    }),
  setEnabled: (dn: string, enabled: boolean) =>
    http.post<{ dn: string; enabled: boolean }>(`/users/enabled?dn=${dnParam(dn)}`, { enabled }),
  unlock: (dn: string) => http.post<{ dn: string }>(`/users/unlock?dn=${dnParam(dn)}`),
  /** null clears the expiry date, i.e. the account never expires. */
  setExpiry: (dn: string, expiresAt: string | null) =>
    http.post<{ dn: string; expires_at: string | null }>(`/users/expiry?dn=${dnParam(dn)}`, {
      expires_at: expiresAt,
    }),
  setMustChangePassword: (dn: string, mustChange: boolean) =>
    http.post<{ dn: string }>(`/users/must-change-password?dn=${dnParam(dn)}`, {
      must_change: mustChange,
    }),
  lockedAccounts: () =>
    http.get<{ accounts: DirectoryObject[]; count: number }>('/users/locked'),

  // -- groups ------------------------------------------------------------
  group: (dn: string) => http.get<GroupDetail>(`/groups?dn=${dnParam(dn)}`),
  createGroup: (payload: {
    parent_dn: string
    name: string
    scope?: string
    security?: boolean
    description?: string
  }) => http.post<GroupDetail>('/groups', payload),
  updateGroup: (
    dn: string,
    payload: {
      attributes?: Record<string, string | null>
      scope?: string
      security?: boolean
    },
  ) => http.patch<{ dn: string; applied: Record<string, unknown> }>(`/groups?dn=${dnParam(dn)}`, payload),
  members: (dn: string, recursive = false) =>
    http.get<MemberListing>(`/groups/members?dn=${dnParam(dn)}&recursive=${recursive}`),
  addMembers: (dn: string, members: string[]) =>
    http.post<{ added: string[]; already_members: string[] }>(
      `/groups/members?dn=${dnParam(dn)}`,
      { members },
    ),
  removeMembers: (dn: string, members: string[]) =>
    http.delete<{ removed: string[]; not_members: string[] }>(
      `/groups/members?dn=${dnParam(dn)}`,
      { members },
    ),
  memberOf: (dn: string, recursive = false) =>
    http.get<{ dn: string; groups: DirectoryObject[] }>(
      `/groups/member-of?dn=${dnParam(dn)}&recursive=${recursive}`,
    ),

  // -- computers ---------------------------------------------------------
  computer: (dn: string) => http.get<ComputerDetail>(`/computers?dn=${dnParam(dn)}`),
  createComputer: (payload: { parent_dn: string; name: string; description?: string }) =>
    http.post<ComputerDetail>('/computers', payload),
  updateComputer: (
    dn: string,
    payload: { attributes?: Record<string, string | null>; flags?: Record<string, boolean> },
  ) =>
    http.patch<{ dn: string; applied: Record<string, unknown> }>(
      `/computers?dn=${dnParam(dn)}`,
      payload,
    ),
  resetComputer: (dn: string) => http.post<{ dn: string }>(`/computers/reset?dn=${dnParam(dn)}`),
  lapsStatus: (dn: string) =>
    http.get<{ available: boolean; generation: string | null; expires_at?: string }>(
      `/computers/laps?dn=${dnParam(dn)}`,
    ),
  revealLaps: (dn: string) =>
    http.post<{ password: string; account: string | null; expires_at: string | null }>(
      `/computers/laps/reveal?dn=${dnParam(dn)}`,
    ),

  // -- DNS ---------------------------------------------------------------
  dnsZones: (includeSystem = false) =>
    http.get<{ zones: DnsZone[] }>(`/dns/zones?include_system=${includeSystem}`),
  dnsRecords: (zoneDn: string, zone: string, includeTombstones = false) =>
    http.get<DnsRecordListing>(
      `/dns/records?zone_dn=${dnParam(zoneDn)}&zone=${encodeURIComponent(zone)}` +
        `&include_tombstones=${includeTombstones}`,
    ),
  dnsRecordTypes: () =>
    http.get<{ types: DnsRecordTypeInfo[]; default_ttl: number }>('/dns/record-types'),
  createDnsRecord: (
    zoneDn: string,
    payload: { zone: string; name: string; type: string; data: DnsRecordData; ttl?: number },
  ) => http.post<DnsRecord>(`/dns/records?zone_dn=${dnParam(zoneDn)}`, payload),
  updateDnsRecord: (
    zoneDn: string,
    payload: {
      zone: string
      name: string
      type: string
      old_data: DnsRecordData
      data: DnsRecordData
      ttl?: number
    },
  ) => http.patch<DnsRecord>(`/dns/records?zone_dn=${dnParam(zoneDn)}`, payload),
  deleteDnsRecord: (
    zoneDn: string,
    payload: { zone: string; name: string; type: string; data: DnsRecordData },
  ) =>
    http.delete<{ name: string; type: string; node_deleted: boolean }>(
      `/dns/records?zone_dn=${dnParam(zoneDn)}`,
      payload,
    ),
  createDnsZone: (name: string, partition = 'domain') =>
    http.post<DnsZone>('/dns/zones', { name, partition }),
  deleteDnsZone: (zoneDn: string) =>
    http.delete<{ dn: string }>(`/dns/zones?zone_dn=${dnParam(zoneDn)}`),

  // -- sites and services -------------------------------------------------
  topology: () => http.get<Topology>('/sites/topology'),
  site: (dn: string) => http.get<Site>(`/sites/site?dn=${dnParam(dn)}`),
  createSite: (payload: { name: string; description?: string }) =>
    http.post<Site>('/sites', payload),
  updateSite: (dn: string, payload: { description?: string | null; location?: string | null }) =>
    http.patch<{ dn: string }>(`/sites?dn=${dnParam(dn)}`, payload),
  renameSite: (dn: string, name: string) =>
    http.post<Site>(`/sites/rename?dn=${dnParam(dn)}`, { name }),
  deleteSite: (dn: string) => http.delete<{ dn: string }>(`/sites?dn=${dnParam(dn)}`),

  subnets: () => http.get<{ subnets: Subnet[] }>('/sites/subnets'),
  createSubnet: (payload: {
    name: string
    site_dn?: string | null
    description?: string
    location?: string
  }) => http.post<Subnet>('/sites/subnets', payload),
  updateSubnet: (
    dn: string,
    payload: {
      site_dn?: string | null
      description?: string | null
      location?: string | null
      clear_site?: boolean
    },
  ) => http.patch<{ dn: string }>(`/sites/subnets?dn=${dnParam(dn)}`, payload),
  deleteSubnet: (dn: string) => http.delete<{ dn: string }>(`/sites/subnets?dn=${dnParam(dn)}`),

  siteLinks: () => http.get<{ links: SiteLink[] }>('/sites/links'),
  createSiteLink: (payload: {
    name: string
    site_dns: string[]
    transport?: string
    cost?: number
    replication_interval?: number
    description?: string
  }) => http.post<SiteLink>('/sites/links', payload),
  updateSiteLink: (
    dn: string,
    payload: {
      site_dns?: string[]
      cost?: number
      replication_interval?: number
      description?: string | null
    },
  ) => http.patch<{ dn: string }>(`/sites/links?dn=${dnParam(dn)}`, payload),
  deleteSiteLink: (dn: string) => http.delete<{ dn: string }>(`/sites/links?dn=${dnParam(dn)}`),

  siteServers: (dn: string) =>
    http.get<{ site_dn: string; servers: SiteServer[] }>(`/sites/servers?dn=${dnParam(dn)}`),
  serverConnections: (dn: string) =>
    http.get<{ server_dn: string; connections: ReplicationConnection[] }>(
      `/sites/connections?dn=${dnParam(dn)}`,
    ),
  moveServer: (dn: string, siteDn: string) =>
    http.post<SiteServer>(`/sites/servers/move?dn=${dnParam(dn)}`, { site_dn: siteDn }),

  // -- group policy -------------------------------------------------------
  gpos: () => http.get<{ gpos: Gpo[] }>('/gpos'),
  gpo: (dn: string) => http.get<Gpo>(`/gpos/gpo?dn=${dnParam(dn)}`),
  gpoStatus: (dn: string) => http.get<GpoStatus>(`/gpos/status?dn=${dnParam(dn)}`),
  // Computing and applying are separate calls on purpose: these attributes
  // decide whether a policy runs at all, so the change is shown first.
  gpoRegistration: (dn: string) =>
    http.get<RegistrationDifferences>(`/gpos/registration?dn=${dnParam(dn)}`),
  reconcileGpoRegistration: (dn: string) =>
    http.post<{ changed: Record<string, unknown>; reconciled: boolean }>(
      `/gpos/registration?dn=${dnParam(dn)}`,
    ),
  createGpo: (displayName: string) => http.post<Gpo>('/gpos', { display_name: displayName }),
  updateGpo: (
    dn: string,
    payload: { display_name?: string; machine_enabled?: boolean; user_enabled?: boolean },
  ) => http.patch<Gpo>(`/gpos?dn=${dnParam(dn)}`, payload),
  deleteGpo: (dn: string, force = false) =>
    http.delete<{ dn: string; name: string }>(`/gpos?dn=${dnParam(dn)}&force=${force}`),

  gpoLinks: (dn: string) => http.get<GpoLinkListing>(`/gpos/links?dn=${dnParam(dn)}`),
  linkGpo: (dn: string, gpoDn: string, options: { enabled?: boolean; enforced?: boolean } = {}) =>
    http.post<GpoLinkListing>(`/gpos/links?dn=${dnParam(dn)}`, { gpo_dn: gpoDn, ...options }),
  updateGpoLink: (
    dn: string,
    gpoDn: string,
    changes: { enabled?: boolean; enforced?: boolean; order?: number },
  ) => http.patch<GpoLinkListing>(`/gpos/links?dn=${dnParam(dn)}`, { gpo_dn: gpoDn, ...changes }),
  unlinkGpo: (dn: string, gpoDn: string) =>
    http.delete<GpoLinkListing>(`/gpos/links?dn=${dnParam(dn)}`, { gpo_dn: gpoDn }),
  gpoLocations: (guid: string) =>
    http.get<{ guid: string; links: GpoLinkLocation[] }>(
      `/gpos/linked?guid=${encodeURIComponent(guid)}`,
    ),

  gpoReport: (dn: string) => http.get<GpoReport>(`/gpos/report?dn=${dnParam(dn)}`),
  downloadGpoReport: (dn: string, name: string) =>
    http.download(`/gpos/report.html?dn=${dnParam(dn)}`, `${name}.html`),
  copyGpo: (dn: string, displayName: string) =>
    http.post<Gpo>(`/gpos/copy?dn=${dnParam(dn)}`, { display_name: displayName }),
  downloadGpoBackup: (dn: string, name: string) =>
    http.download(`/gpos/backup?dn=${dnParam(dn)}`, `${name}.zip`),
  restoreGpo: (archive: File, displayName?: string) =>
    http.upload<Gpo>(
      displayName
        ? `/gpos/restore?display_name=${encodeURIComponent(displayName)}`
        : '/gpos/restore',
      'archive',
      archive,
    ),

  wmiFilters: () => http.get<{ filters: WmiFilter[] }>('/gpos/wmi-filters'),
  gpoWmiFilter: (dn: string) =>
    http.get<{ filter: WmiFilter | null }>(`/gpos/wmi-filter?dn=${dnParam(dn)}`),
  assignWmiFilter: (dn: string, filterDn: string | null) =>
    http.post<Gpo>(`/gpos/wmi-filter?dn=${dnParam(dn)}`, { filter_dn: filterDn }),

  gpoInheritance: (dn: string) => http.get<GpoInheritance>(`/gpos/inheritance?dn=${dnParam(dn)}`),
  blockInheritance: (dn: string, block: boolean) =>
    http.post<GpoLinkListing>(`/gpos/inheritance?dn=${dnParam(dn)}`, { block }),
  gpoFiltering: (dn: string) => http.get<GpoFiltering>(`/gpos/filtering?dn=${dnParam(dn)}`),

  // -- administrative templates -------------------------------------------
  admxStore: () => http.get<AdmxStore>('/admx/store'),
  uploadTemplates: (file: File, overwrite = false) =>
    http.upload<{ path: string; added: string[] }>(
      `/admx/store?overwrite=${overwrite}`,
      'files',
      file,
    ),
  bundledTemplates: () => http.get<AdmxBundled>('/admx/bundled'),
  installBundledTemplates: (overwrite = false) =>
    http.post<{ path: string; added: string[] }>(`/admx/bundled?overwrite=${overwrite}`),
  refreshTemplates: () => http.post<{ policies: number }>('/admx/refresh'),
  // `dn` is what makes the listing carry each setting's state in this GPO —
  // the status column. Without it the tree is just the store.
  // `configured` cuts the level down to what this GPO actually sets — a
  // question only the server can answer, since the browser holds one level and
  // a branch worth showing may have its settings three levels further down.
  admxTree: (
    category: string | null,
    half: string,
    dn?: string,
    language?: string,
    configured = false,
  ) =>
    http.get<AdmxTree>(
      `/admx/tree?half=${half}` +
        (category ? `&category=${encodeURIComponent(category)}` : '') +
        (dn ? `&dn=${dnParam(dn)}` : '') +
        (language ? `&language=${encodeURIComponent(language)}` : '') +
        (configured ? '&configured=true' : ''),
    ),
  admxPolicy: (id: string, language?: string) =>
    http.get<AdmxPolicy>(
      `/admx/policy?id=${encodeURIComponent(id)}` +
        (language ? `&language=${encodeURIComponent(language)}` : ''),
    ),
  admxSearch: (query: string, half: string, dn?: string, language?: string) =>
    http.get<{ query: string; policies: AdmxPolicySummary[] }>(
      `/admx/search?q=${encodeURIComponent(query)}&half=${half}` +
        (dn ? `&dn=${dnParam(dn)}` : '') +
        (language ? `&language=${encodeURIComponent(language)}` : ''),
    ),
  admxState: (dn: string, id: string, half: string) =>
    http.get<AdmxState>(
      `/admx/state?dn=${dnParam(dn)}&id=${encodeURIComponent(id)}&half=${half}`,
    ),
  applyPolicy: (
    dn: string,
    payload: {
      policy: string
      half: string
      state: PolicyState
      values?: Record<string, unknown>
      expected_version?: number
    },
  ) => http.post<AdmxApplyResult>(`/admx/state?dn=${dnParam(dn)}`, payload),

  // -- scripts ------------------------------------------------------------
  gpoScripts: (dn: string, half: string) =>
    http.get<GpoScripts>(`/gpos/scripts?dn=${dnParam(dn)}&half=${half}`),
  // The complete list for one event and engine: the numbering in the file is
  // the execution order and has to be gapless, so reordering and removing are
  // the same operation as adding.
  setGpoScripts: (
    dn: string,
    payload: {
      half: string
      event: ScriptEvent
      engine: ScriptEngine
      scripts: { command: string; parameters: string }[]
      ps_first?: boolean | null
      expected_version?: number
    },
  ) => http.post<AdmxApplyResult>(`/gpos/scripts?dn=${dnParam(dn)}`, payload),

  // The files themselves, which are not the same thing as the list of
  // scripts to run: a helper another script calls belongs on the share
  // without being scheduled.
  gpoScriptFiles: (dn: string, half: string, event: string) =>
    http.get<{ files: ScriptFile[] }>(
      `/gpos/scripts/files?dn=${dnParam(dn)}&half=${half}&event=${event}`,
    ),
  uploadGpoScriptFile: (dn: string, half: string, event: string, file: File) =>
    http.upload<{ name: string; size: number }>(
      `/gpos/scripts/files?dn=${dnParam(dn)}&half=${half}&event=${event}`,
      'file',
      file,
    ),
  downloadGpoScriptFile: (dn: string, half: string, event: string, name: string) =>
    http.download(
      `/gpos/scripts/files/content?dn=${dnParam(dn)}&half=${half}&event=${event}` +
        `&name=${encodeURIComponent(name)}`,
      name,
    ),
  deleteGpoScriptFile: (dn: string, half: string, event: string, name: string) =>
    http.delete<{ removed: string }>(
      `/gpos/scripts/files?dn=${dnParam(dn)}&half=${half}&event=${event}` +
        `&name=${encodeURIComponent(name)}`,
    ),

  // -- Samba's own policies (VGP) -----------------------------------------
  // Windows clients ignore these; samba-gpupdate applies them on Linux
  // members. No client-side extension is registered, deliberately.
  vgpKinds: () => http.get<{ kinds: VgpKind[] }>('/gpos/vgp/kinds'),
  vgpPayloads: (dn: string, policy: string) =>
    http.get<{ payloads: VgpPayload[] }>(
      `/gpos/vgp/payloads?dn=${dnParam(dn)}&policy=${policy}`,
    ),
  uploadVgpPayload: (dn: string, policy: string, file: File) =>
    http.upload<{ name: string; size: number }>(
      `/gpos/vgp/payloads?dn=${dnParam(dn)}&policy=${policy}`,
      'file',
      file,
    ),
  gpoVgp: (dn: string) => http.get<GpoVgp>(`/gpos/vgp?dn=${dnParam(dn)}`),
  // The complete list for one policy: a manifest holds the whole list, so
  // reordering and removing are the same operation as adding.
  setGpoVgp: (
    dn: string,
    payload: { policy: VgpPolicy; entries: VgpEntry[]; expected_version?: number },
  ) => http.post<AdmxApplyResult>(`/gpos/vgp?dn=${dnParam(dn)}`, payload),

  // A restricted group is two keys, not one. Removing it clears both in a
  // single write; two writes would raise the version in between and the
  // second would be refused as somebody else's change.
  setRestrictedGroup: (
    dn: string,
    payload: { sid: string; present: boolean; expected_version?: number },
  ) => http.post<AdmxApplyResult>(`/gpos/security/restricted-group?dn=${dnParam(dn)}`, payload),

  // -- group policy preferences -------------------------------------------
  // One file per type per half, each with its own client-side extension. The
  // catalogue comes from the server so that adding a type is a change there
  // and not here.
  preferenceTypes: () =>
    http.get<{ actions: PreferenceAction[]; types: PreferenceType[] }>(
      '/gpos/preferences/types',
    ),
  gpoPreferences: (dn: string) =>
    http.get<GpoPreferences>(`/gpos/preferences?dn=${dnParam(dn)}`),
  // The complete list for one type of one half. Filters are deliberately not
  // part of it: the server keeps the ones already in the file.
  setGpoPreferences: (
    dn: string,
    payload: {
      type: PreferenceTypeId
      half: string
      items: {
        kind?: string
        uid?: string
        action?: PreferenceAction
        properties: Record<string, string>
        values?: string[]
        members?: PreferenceMember[]
      }[]
      expected_version?: number
    },
  ) => http.post<AdmxApplyResult>(`/gpos/preferences?dn=${dnParam(dn)}`, payload),

  // -- security settings --------------------------------------------------
  // The file carries no types, so the catalogue is where the editor learns
  // that a lockout duration counts minutes and an audit category has four
  // states.
  securityCatalogue: () => http.get<SecurityCatalogue>('/gpos/security/catalogue'),
  gpoSecurity: (dn: string) => http.get<GpoSecurity>(`/gpos/security?dn=${dnParam(dn)}`),
  // A string for a plain setting, a list of SIDs for a user right or a
  // restricted group; null means "not defined".
  setGpoSecurity: (
    dn: string,
    payload: {
      section: string
      key: string
      value: string | string[] | null
      expected_version?: number
    },
  ) => http.post<AdmxApplyResult>(`/gpos/security?dn=${dnParam(dn)}`, payload),

  // -- folder redirection -------------------------------------------------
  knownFolders: () =>
    http.get<{ folders: { guid: string; name: string }[] }>('/gpos/redirection/folders'),
  gpoRedirection: (dn: string) =>
    http.get<GpoRedirection>(`/gpos/redirection?dn=${dnParam(dn)}`),
  // One folder, one group. A null path stops redirecting that pairing.
  redirectFolder: (
    dn: string,
    payload: {
      folder: string
      sid: string
      path: string | null
      expected_version?: number
    },
  ) => http.post<AdmxApplyResult>(`/gpos/redirection?dn=${dnParam(dn)}`, payload),

  // -- diagnostics --------------------------------------------------------
  diagnostics: () => http.get<DiagnosticsOverview>('/diagnostics'),
  securityFindings: (area: FindingArea, deep = false) =>
    http.get<FindingsReport>(`/diagnostics/findings?area=${area}&deep=${deep}`),
  /** Both reports in full, gathered in one pass so the timestamp holds. */
  domainReport: (deep = false) =>
    http.get<DomainReport>(`/diagnostics/report?deep=${deep}`),

  // -- the optional model service ----------------------------------------
  assistant: () => http.get<AssistantStatus>('/assistant'),
  assistantModels: () => http.get<{ models: OllamaModel[] }>('/assistant/models'),
  /** What would be sent. Fetched before sending, not described. */
  assistantPayload: (language: string, area: FindingArea, deep = false) =>
    http.get<AssistantPayload>(
      `/assistant/payload?language=${language}&area=${area}&deep=${deep}`,
    ),
  assistantReport: (model: string, language: string, area: FindingArea, deep = false) =>
    http.post<AssistantReport>(
      `/assistant/report?model=${encodeURIComponent(model)}` +
        `&language=${language}&area=${area}&deep=${deep}`,
    ),
  passwordPolicy: () => http.get<PasswordPolicy>('/diagnostics/policy'),
  problemAccounts: (limit = 200) =>
    http.get<AccountProblems>(`/diagnostics/accounts?limit=${limit}`),

  // -- permissions -------------------------------------------------------
  acl: (dn: string) => http.get<AclListing>(`/security/acl?dn=${dnParam(dn)}`),
  addAce: (
    dn: string,
    payload: {
      trustee_sid: string
      mask: number
      deny?: boolean
      object_guid?: string | null
      applies_to_guid?: string | null
      inherit_to_children?: boolean
      expected_sddl?: string
    },
  ) => http.post<{ dn: string; added: string }>(`/security/acl/entries?dn=${dnParam(dn)}`, payload),
  removeAce: (dn: string, index: number, expectedSddl?: string) =>
    http.delete<{ dn: string; removed: string }>(`/security/acl/entries?dn=${dnParam(dn)}`, {
      index,
      expected_sddl: expectedSddl ?? null,
    }),
  delegationTemplates: () =>
    http.get<{ templates: DelegationTemplate[] }>('/security/delegation/templates'),
  delegate: (dn: string, templateId: string, trusteeSid: string, expectedSddl?: string) =>
    http.post<{ dn: string; applied: string[] }>(`/security/delegation?dn=${dnParam(dn)}`, {
      template_id: templateId,
      trustee_sid: trusteeSid,
      expected_sddl: expectedSddl ?? null,
    }),
  setDeleteProtection: (dn: string, protect: boolean) =>
    http.post<{ dn: string; delete_protected: boolean }>(
      `/security/protection?dn=${dnParam(dn)}`,
      { protect },
    ),

  // -- organizational units ---------------------------------------------
  ou: (dn: string) => http.get<OuDetail>(`/ous?dn=${dnParam(dn)}`),
  createOu: (payload: {
    parent_dn: string
    name: string
    description?: string
    protect_from_deletion?: boolean
  }) => http.post<OuDetail>('/ous', payload),
  updateOu: (dn: string, payload: { attributes?: Record<string, string | null>; protect_from_deletion?: boolean }) =>
    http.patch<{ dn: string }>(`/ous?dn=${dnParam(dn)}`, payload),
  deleteOu: (dn: string, recursive = false) =>
    http.delete<{ dn: string }>(`/ous?dn=${dnParam(dn)}&recursive=${recursive}`),
}
